"""
Nova LLM Engine
Provides seamless local LLM capabilities via Ollama (e.g. qwen2.5:3b).
Supports:
- Zero external API keys (100% local and offline)
- Complex multi-step command decomposition and parsing into structured tool actions
- Text, document, and context summarization
- Resilient local fallback algorithms if Ollama is not active
"""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nova.llm")


class OllamaClient:
    """Local LLM client communicating with Ollama REST API on localhost."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        preferred_model: str = "qwen2.5:3b",
        timeout: int = 40,
    ):
        self.base_url = base_url.rstrip("/")
        self.preferred_model = preferred_model
        self.timeout = timeout
        self._model: Optional[str] = None
        self._is_available: Optional[bool] = None

    def is_available(self, force_check: bool = False) -> bool:
        """Checks if local Ollama daemon is reachable and has models loaded."""
        if self._is_available is not None and not force_check:
            return self._is_available

        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as res:
                if res.status == 200:
                    data = json.loads(res.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    if models:
                        # Match preferred model or prefix
                        for m in models:
                            if self.preferred_model in m:
                                self._model = m
                                break
                        if not self._model and models:
                            self._model = models[0]
                        self._is_available = True
                        return True
        except Exception as e:
            logger.debug(f"Ollama not reachable: {e}")

        self._is_available = False
        return False

    @property
    def model_name(self) -> str:
        if self._model:
            return self._model
        return self.preferred_model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """Sends a generation request to the local Ollama instance."""
        if not self.is_available():
            return None

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    return res_json.get("response", "").strip()
        except Exception as e:
            logger.warning(f"Ollama generation failed: {e}")
            return None

        return None

    def summarize(
        self,
        text: str,
        context: Optional[str] = None,
        max_words: Optional[int] = None,
    ) -> str:
        """
        Summarizes text or context using local Ollama.
        Falls back to intelligent local extractive summarizer if Ollama is unreachable.
        """
        cleaned_text = text.strip()
        if not cleaned_text:
            return "No content provided to summarize."

        # If short text, return directly
        words = cleaned_text.split()
        if len(words) <= 25 and not context:
            return cleaned_text

        if self.is_available():
            system_prompt = (
                "You are NOVA, a smart virtual assistant. "
                "Provide an accurate, clear, and well-structured summary. "
                "Highlight key points, main conclusions, and actionable takeaways using bullet points or concise paragraphs."
            )
            prompt = f"Summarize the following content concisely:\n\n{cleaned_text}"
            if context:
                prompt = f"Context/History:\n{context}\n\n" + prompt

            llm_summary = self.generate(prompt=prompt, system_prompt=system_prompt)
            if llm_summary:
                return llm_summary

        # Resilient local fallback if Ollama is not active or times out
        return self._local_extractive_summary(cleaned_text, max_sentences=4)

    def parse_complex_command(
        self,
        utterance: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Decomposes complex, conversational, or compound commands into a sequence
        of structured action intents.
        """
        if not self.is_available():
            return None

        system_prompt = (
            "You are the central brain parser of virtual assistant NOVA.\n"
            "Analyze the user command and decompose it into a sequential list of concrete actions in JSON format.\n\n"
            "Supported intents:\n"
            "1. CREATE_FOLDER: {\"intent\": \"CREATE_FOLDER\", \"name\": \"<folder_name>\", \"parent\": \"<optional_parent_folder_or_null>\"}\n"
            "2. CREATE_FILE: {\"intent\": \"CREATE_FILE\", \"name\": \"<file_name>\", \"parent\": \"<optional_parent_folder_or_null>\", \"content\": \"<optional_content>\"}\n"
            "3. RENAME_ITEM: {\"intent\": \"RENAME_ITEM\", \"old_name\": \"<old>\", \"new_name\": \"<new>\", \"is_dir\": true/false/null}\n"
            "4. DELETE_ITEM: {\"intent\": \"DELETE_ITEM\", \"name\": \"<name>\", \"is_dir\": true/false/null, \"permanent\": true/false}\n"
            "5. COPY_ITEM: {\"intent\": \"COPY_ITEM\", \"source\": \"<src>\", \"destination\": \"<dest>\"}\n"
            "6. MOVE_ITEM: {\"intent\": \"MOVE_ITEM\", \"source\": \"<src>\", \"destination\": \"<dest>\"}\n"
            "7. OPEN_APP: {\"intent\": \"OPEN_APP\", \"name\": \"<app_name>\"}\n"
            "8. OPEN_ITEM: {\"intent\": \"OPEN_ITEM\", \"name\": \"<item_name>\", \"kind\": \"file\"/\"folder\"/null}\n"
            "9. FIND_ITEM: {\"intent\": \"FIND_ITEM\", \"query\": \"<search_query>\", \"kind\": \"any\"/\"app\"/\"file\"/\"folder\"}\n"
            "10. SUMMARIZE: {\"intent\": \"SUMMARIZE\", \"target_type\": \"text\"/\"file\"/\"context\", \"target\": \"<text_or_file_name>\"}\n"
            "11. POWER: {\"intent\": \"POWER\", \"action\": \"lock\"/\"sleep\"/\"restart\"/\"shutdown\"/\"abort\"/\"battery\", \"delay\": 0}\n"
            "12. LANGUAGE_CHART: {\"intent\": \"LANGUAGE_CHART\"}\n\n"
            "Context rules:\n"
            "- If a command creates a folder 'X' in 'Y', and then creates a file 'Z', the file 'Z' parent is usually 'X' unless specified otherwise.\n"
            "- Strip surrounding quotes from names.\n"
            "- Return JSON with key 'steps' containing the ordered array of action objects.\n"
            "Example output: {\"steps\": [{\"intent\": \"CREATE_FOLDER\", \"name\": \"Demo\", \"parent\": \"Project\"}, {\"intent\": \"CREATE_FILE\", \"name\": \"xyz.txt\", \"parent\": \"Demo\", \"content\": \"\"}]}"
        )

        user_prompt = f"User Command: \"{utterance}\""
        if context:
            user_prompt += f"\nCurrent context: {json.dumps(context)}"

        raw_resp = self.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_mode=True,
            temperature=0.1,
        )
        if not raw_resp:
            return None

        try:
            data = json.loads(raw_resp)
            steps = data.get("steps", [])
            if isinstance(steps, list) and len(steps) > 0:
                normalized_steps = []
                for s in steps:
                    if isinstance(s, dict):
                        # Support both {"intent": ..., ...} and {"action": ..., "details": {...}} formats
                        if "action" in s and "intent" not in s:
                            s["intent"] = s["action"]
                        if "details" in s and isinstance(s["details"], dict):
                            for k, v in s["details"].items():
                                s.setdefault(k, v)
                        normalized_steps.append(s)
                return normalized_steps
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON from LLM: {raw_resp}")

        return None

    @staticmethod
    def _local_extractive_summary(text: str, max_sentences: int = 4) -> str:
        """
        Extractive summarizer: scores sentences based on term frequencies and positions.
        Used as a dependable offline fallback when Ollama is not active.
        """
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) <= max_sentences:
            return text.strip()

        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        stopwords = {
            "the", "and", "that", "have", "for", "not", "with", "you", "this",
            "but", "his", "from", "they", "say", "her", "she", "will", "one",
            "all", "would", "there", "their", "what", "out", "about", "who",
            "get", "which", "when", "make", "can", "like", "time", "just",
            "him", "know", "take", "people", "into", "year", "your", "good",
            "some", "could", "them", "see", "other", "than", "then", "now",
            "look", "only", "come", "its", "over", "think", "also", "back",
            "after", "use", "two", "how", "our", "work", "first", "well",
            "way", "even", "new", "want", "because", "any", "these", "give",
            "most", "us", "are", "was", "were", "been", "has", "had",
        }
        word_freq: Dict[str, int] = {}
        for w in words:
            if w not in stopwords:
                word_freq[w] = word_freq.get(w, 0) + 1

        sentence_scores = []
        for idx, sentence in enumerate(sentences):
            s_words = re.findall(r"\b[a-zA-Z]{3,}\b", sentence.lower())
            if not s_words:
                continue
            score = sum(word_freq.get(w, 0) for w in s_words) / (len(s_words) ** 0.5)
            # Give slight boost to first and last sentences
            if idx == 0:
                score *= 1.3
            elif idx == len(sentences) - 1:
                score *= 1.1
            sentence_scores.append((score, idx, sentence))

        sentence_scores.sort(reverse=True, key=lambda x: x[0])
        top_sentences = sorted(sentence_scores[:max_sentences], key=lambda x: x[1])

        summary_bullets = [f"• {item[2].strip()}" for item in top_sentences if item[2].strip()]
        return "\n".join(summary_bullets)
