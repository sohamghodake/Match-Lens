"""Which models can an API key use, and what are its rate limits?

    python -m scripts.provider_info groq                          # list the key's models
    python -m scripts.provider_info groq --probe MODEL [MODEL...]  # plus each model's limits

`--probe` sends one tiny request per model (a one-word prompt, max 1 output token) and
reads the x-ratelimit-* response headers: requests per day, tokens per minute, and how
much is left. On a free tier this costs nothing. The key itself is never printed.
"""

import argparse
import sys

import httpx

from app.llm.providers import PRESETS

# What the x-ratelimit-* headers mean on Groq (https://console.groq.com/docs/rate-limits).
HEADER_MEANING = {
    "x-ratelimit-limit-requests": "requests per day (limit)",
    "x-ratelimit-remaining-requests": "requests per day (left)",
    "x-ratelimit-reset-requests": "requests reset in",
    "x-ratelimit-limit-tokens": "tokens per minute (limit)",
    "x-ratelimit-remaining-tokens": "tokens per minute (left)",
    "x-ratelimit-reset-tokens": "tokens reset in",
    "retry-after": "retry after (s)",
}


def _error(response: httpx.Response) -> str:
    try:
        err = response.json().get("error", {})
        return err.get("message") or str(err)
    except ValueError:
        return response.text[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("provider", choices=sorted(PRESETS))
    parser.add_argument("--probe", nargs="*", default=[], metavar="MODEL")
    args = parser.parse_args()

    preset = PRESETS[args.provider]
    key = preset.api_key()
    if not key:
        print(f"{preset.api_key_env} is not set. Add it to .env, then recreate the backend:")
        print("  docker compose up -d backend")
        return 1
    print(f"{preset.api_key_env}: set ({key[:4]}…, {len(key)} characters)")

    with httpx.Client(
        base_url=preset.base_url, headers={"Authorization": f"Bearer {key}"}, timeout=30
    ) as client:
        response = client.get("/models")
        if response.status_code != 200:
            print(f"✗ /models returned HTTP {response.status_code}: {_error(response)}")
            return 1
        models = sorted(response.json().get("data", []), key=lambda m: m["id"])
        print(f"\n{len(models)} models available to this key:")
        print(f"  {'model':<46} {'context':>8} {'max output':>10}  owner")
        for m in models:
            context = m.get("context_window") or ""
            output = m.get("max_completion_tokens") or ""
            print(f"  {m['id']:<46} {context!s:>8} {output!s:>10}  {m.get('owned_by', '')}")

        for model in args.probe:
            print(f"\n▶ {model}")
            r = client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 1,
                },
            )
            status = "ok" if r.status_code == 200 else f"HTTP {r.status_code}: {_error(r)}"
            print(f"  request: {status}")
            for header, meaning in HEADER_MEANING.items():
                if header in r.headers:
                    print(f"  {meaning:<28} {r.headers[header]}")
            if not any(h in r.headers for h in HEADER_MEANING):
                print("  (no rate-limit headers in the response)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
