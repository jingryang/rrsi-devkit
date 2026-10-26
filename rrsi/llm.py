# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Claude client for the three search roles (proposer, analyst, critic).

Claude Opus 4.8 via AnthropicVertex, round-robin over the configured GCP
projects with retry-and-rotate on failure. When no Vertex project is configured
the same messages API is served by an Anthropic-compatible local gateway
(``RRSI_ANTHROPIC_BASE_URL`` + ``RRSI_ANTHROPIC_API_KEY``). `cache_prefix`
sends a large stable leading block (constitution + harness source) as its own
ephemeral-cached content block so repeated turns pay to read it once.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import threading
import time

MODEL = os.environ.get("RRSI_SEARCH_MODEL", "claude-opus-4-8")
_PROJECTS = [
    {"project_id": p.strip(), "region": os.environ.get("RRSI_VERTEX_REGION", "global")}
    for p in os.environ.get("RRSI_VERTEX_PROJECTS", "").split(",")
    if p.strip()
]
# Anthropic-compatible gateway used when no Vertex project is configured.
_BASE_URL = (os.environ.get("RRSI_ANTHROPIC_BASE_URL")
             or os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
_API_KEY = (os.environ.get("RRSI_ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_API_KEY") or "")
MAX_TOKENS = 20_000

_clients: dict = {}
_clients_lock = threading.Lock()
_rr = itertools.count()
_JSON_SUFFIX = ("\n\nOutput ONLY a single valid JSON object. No prose before or "
                "after, no markdown fences, no XML or tool-call syntax, no "
                "second object.")


def _client_for(idx: int):
    if not _PROJECTS:
        if not (_BASE_URL and _API_KEY):
            raise RuntimeError(
                "set RRSI_VERTEX_PROJECTS to a comma-separated list of GCP "
                "projects with Claude on Vertex AI enabled, or point the "
                "search roles at an Anthropic-compatible gateway with "
                "RRSI_ANTHROPIC_BASE_URL + RRSI_ANTHROPIC_API_KEY")
        from anthropic import Anthropic
        with _clients_lock:
            c = _clients.get("gateway")
            if c is None:
                c = Anthropic(base_url=_BASE_URL, api_key=_API_KEY)
                _clients["gateway"] = c
            return c
    from anthropic import AnthropicVertex
    with _clients_lock:
        c = _clients.get(idx)
        if c is None:
            c = AnthropicVertex(**_PROJECTS[idx])
            _clients[idx] = c
        return c


_DSML_INVOKE = re.compile(
    r"<invoke\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"(?=</invoke>|(?=<invoke\b)|$)",
    re.S)
_DSML_PARAM = re.compile(
    r"<parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"(?=</parameter>|(?=<parameter\b)|(?=</invoke>)|\Z)",
    re.S)


def dsml_actions(text: str) -> list[dict]:
    """Parse a model's native tool-call blocks into action dicts.

    Some gateway models answer with their internal DSML/XML tool syntax
    (``<invoke name="bash"><parameter name="cmd">...</parameter></invoke>``)
    even when asked for JSON. Translating it here keeps every role loop on one
    protocol instead of each one re-learning the same failure.
    """
    # The gateway renders the DSML token as "<｜DSML｜ invoke ...>" / "<｜DSML｜ calls>".
    text = re.sub(r"<(/?)｜DSML｜\s+", r"<\1", text)
    out = []
    for name, body in _DSML_INVOKE.findall(text):
        act: dict = {"action": name}
        for key, raw in _DSML_PARAM.findall(body):
            value = raw.strip()
            try:
                act[key] = json.loads(value)
            except json.JSONDecodeError:
                act[key] = value
        out.append(act)
    return out


def extract_json(text: str) -> str:
    """Return the first complete JSON value, tolerating prose and fences.

    Models routinely append an explanation or a second object after the
    requested one; taking the first decodable value keeps the role loop alive
    instead of burning a turn on "invalid JSON".
    """
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        return t
    start = min(starts)
    try:
        _, end = json.JSONDecoder().raw_decode(t[start:])
    except json.JSONDecodeError:
        return t[start:]
    return t[start:start + end]


def generate(prompt: str, system: str | None = None, max_retries: int = 6,
             json_only: bool = False, model: str | None = None,
             max_tokens: int = MAX_TOKENS, cache_prefix: str | None = None) -> str:
    mdl = model or MODEL
    sys_prompt = (system or "") + (_JSON_SUFFIX if json_only else "")
    content = ([{"type": "text", "text": cache_prefix,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt}] if cache_prefix else prompt)
    n = len(_PROJECTS) or 1
    start = next(_rr)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        idx = (start + attempt) % n
        try:
            client = _client_for(idx)
            kwargs = {"model": mdl, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": content}]}
            if sys_prompt:
                kwargs["system"] = sys_prompt
            resp = client.messages.create(**kwargs)
            text = "".join(b.text for b in resp.content
                           if getattr(b, "type", "") == "text")
            if text:
                if not json_only:
                    return text
                acts = dsml_actions(text)
                if acts:
                    return json.dumps(acts if len(acts) > 1 else acts[0],
                                      ensure_ascii=False)
                return extract_json(text)
            last_err = RuntimeError("empty response")
            # An empty 200 is still a gateway failure; back off instead of
            # hammering it with six immediate retries.
            time.sleep(min(2 ** attempt, 30))
        except Exception as e:  # noqa: BLE001 - rotate to the other project
            last_err = e
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"generate failed after {max_retries} tries: {last_err}")


if __name__ == "__main__":
    print(generate("Reply with exactly: OK", max_tokens=16))
