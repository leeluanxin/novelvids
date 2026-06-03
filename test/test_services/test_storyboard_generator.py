import json

from services.storyboard.generator import _parse_storyboard_content


def _shot(sequence: int = 1) -> dict:
    return {
        "sequence": sequence,
        "description": f"shot-{sequence}",
        "duration": "4s",
        "visual_prose": "A detailed frame.",
        "actions": ["0.0s-2.0s: action"],
        "format_and_look": "65mm",
        "lenses_and_filtration": "50mm prime",
        "lighting_and_atmosphere": "Soft light",
        "grade_and_palette": "Warm",
        "camera_movement": "Slow push in",
        "sound_design": "Room tone",
    }


def test_解析分镜_对象结构():
    storyboard = _parse_storyboard_content(json.dumps({"shots": [_shot()]}))

    assert len(storyboard.shots) == 1
    assert storyboard.shots[0].sequence == 1
    assert storyboard.shots[0].duration == 4.0


def test_解析分镜_裸数组结构():
    storyboard = _parse_storyboard_content(json.dumps([_shot(1), _shot(2)]))

    assert len(storyboard.shots) == 2
    assert storyboard.shots[1].sequence == 2


def test_解析分镜_混合输出中恢复_json():
    content = "Storyboard result:\n" + json.dumps([_shot()]) + "\nDone."

    storyboard = _parse_storyboard_content(content)

    assert len(storyboard.shots) == 1
    assert storyboard.shots[0].description == "shot-1"


def test_解析分镜_数字时长结构():
    shot = _shot()
    shot["duration"] = 4.5

    storyboard = _parse_storyboard_content(json.dumps({"shots": [shot]}))

    assert len(storyboard.shots) == 1
    assert storyboard.shots[0].duration == 4.5
