#!/usr/bin/env python3
"""Test script for improved creative preset generation."""

import json
import requests
from examples.grok_wechat_server import generate_creative_presets, complete_creative_preset

def test_generate_presets():
    """Test generating creative presets from a brief."""
    print("=" * 80)
    print("TEST 1: Generate creative presets from brief")
    print("=" * 80)

    payload = {
        "brief": "AI成为每个人的第二大脑，未来生活会发生哪些具体变化",
        "count": 3,
    }

    try:
        result = generate_creative_presets(payload)
        print(f"✅ Generated {len(result['presets'])} presets\n")

        for i, preset in enumerate(result["presets"], 1):
            print(f"Preset {i}: {preset.get('name')}")
            print(f"  Topic: {preset.get('topic')}")
            print(f"  Audience: {preset.get('audience')}")
            print(f"  Tone: {preset.get('tone')}")
            print(f"  Sections: {preset.get('section_count')}")
            print(f"  Image style: {preset.get('image_style')}\n")

        return result["presets"]
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_complete_preset():
    """Test completing a partial preset."""
    print("=" * 80)
    print("TEST 2: Complete a partial preset")
    print("=" * 80)

    payload = {
        "idea": "关于未来城市生活的想象",
        "preset": {
            "name": "未来城市",
            "topic": "未来城市中的智能生活",
            # 其他字段缺失，让模型补全
        },
    }

    try:
        result = complete_creative_preset(payload)
        print("✅ Completed preset:\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_text_generation_fallback():
    """Test text generation with model fallback."""
    print("=" * 80)
    print("TEST 3: Text generation with model fallback")
    print("=" * 80)

    test_prompt = "用一句话描述WeChat公众号的特点"

    models_to_test = [
        ("grok", "grok-4-fast-reasoning"),  # 可能会超载
        ("grok", "grok-3-mini"),  # 备用
    ]

    for provider, model in models_to_test:
        print(f"\nTrying {provider}/{model}...")
        try:
            response = requests.post(
                "https://images.vyibc.com/api/v1beta/text:generate",
                json={"provider": provider, "model": model, "prompt": test_prompt},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                print(f"  ❌ Failed: {data.get('error', {}).get('message')}")
            else:
                print(f"  ✅ Success: {data.get('text')}")
                break
        except Exception as e:
            print(f"  ❌ Error: {e}")


if __name__ == "__main__":
    print("\n🧪 Testing improved creative preset generation\n")

    # Test 1: Generate presets
    presets = test_generate_presets()

    # Test 2: Complete preset
    if presets:
        test_complete_preset()

    # Test 3: Fallback
    test_text_generation_fallback()

    print("\n" + "=" * 80)
    print("Tests completed!")
    print("=" * 80)
