# -*- coding: utf-8 -*-
"""
run_all_tests.py - 전체 검증 통합 실행기
─────────────────────────────────────────────────────────────
테스트 파일이 4종으로 늘어 개별 실행이 번거로워졌으므로 한 번에 돌린다.

실행
    python run_all_tests.py            # 전체
    python run_all_tests.py 2 3        # 2번·3번만
    python run_all_tests.py -v         # 개별 항목까지 전부 출력

종료 코드
    0 = 전체 통과 / 1 = 실패 있음  (CI 연동 가능)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ── Windows 한글 콘솔(cp949) 출력 호환 ────────────────────────
# cp949 에는 ═ ✅ ❌ 💥 ⬜ ⚠️ 문자가 없어 그대로 출력하면
# UnicodeEncodeError 로 프로그램이 중단된다. 아래에서 두 겹으로 막는다.
#   ① 스트림 errors="replace"  → 어떤 문자가 와도 중단되지 않음
#   ② 인코딩이 좁으면 ASCII 기호로 자동 대체 → 화면이 깨지지 않음
def _init_console():
    for _name in ("stdout", "stderr"):
        _stream = getattr(sys, _name, None)
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass
    import os
    _plain = {"bar": "=", "ok": "[OK]", "no": "[FAIL]", "boom": "[ERROR]",
              "none": "[NONE]", "warn": "[!]"}
    if os.getenv("PTS_ASCII") == "1":      # 실행기가 좁은 콘솔이라고 알려준 경우
        return _plain
    _enc = (getattr(sys.stdout, "encoding", "") or "ascii")
    try:
        "═✅❌💥⬜".encode(_enc)
        return {"bar": "═", "ok": "✅", "no": "❌", "boom": "💥",
                "none": "⬜", "warn": "⚠️"}
    except Exception:
        return _plain


SYM = _init_console()
BAR = SYM["bar"]

SUITES = [
    ("1", "test_1_core.py", "기반 패치 ①~⑤",
     "구분 체계 · 상태 관리 · Result 타입 · 콤마 금액 파싱"),
    ("2", "test_2_boq.py", "① 일위대가 전개",
     "세트 단가 산출 · 중첩 · 순환 참조 · 비목 정확화"),
    ("3", "test_3_advanced.py", "②③④ 설계서 3종",
     "수량산출서 · CPM 공정표 · 설계변경 대비표"),
    ("4", "test_4_auth.py", "⑥ 편집 권한 (보류)",
     "비밀번호 해시 · 세션 TTL · 무단 대입 잠금"),
]

# ASCII 전용 기계판독 줄. 인코딩이 어긋나도 절대 깨지지 않는다.
_PTS_RESULT_RE = re.compile(r"PTS_RESULT\s+PASS=(\d+)\s+FAIL=(\d+)")


def _safe(text):
    """콘솔이 표현할 수 없는 문자를 걸러 출력 중단을 막는다."""
    enc = (getattr(sys.stdout, "encoding", "") or "ascii")
    try:
        text.encode(enc)
        return text
    except Exception:
        return text.encode(enc, errors="replace").decode(enc, errors="replace")


_RESULT_RE = re.compile(r"결과:\s*(\d+)건 통과\s*/\s*(\d+)건 실패")
_SKIP_RE = re.compile(r"\[SKIP\]")


def run(suite, verbose: bool):
    key, filename, title, detail = suite
    path = BASE / filename

    if not path.exists():
        return {"key": key, "title": title, "state": "missing",
                "passed": 0, "failed": 0, "skipped": 0, "seconds": 0.0}

    child_env = dict(os.environ)
    # 자식 출력을 UTF-8 로 고정해 부모의 디코딩과 어긋나지 않게 한다.
    child_env["PYTHONIOENCODING"] = "utf-8"
    if SYM["bar"] == "=":              # 부모 콘솔이 좁으면 자식도 ASCII 기호 사용
        child_env["PTS_ASCII"] = "1"

    started = time.time()
    proc = subprocess.run([sys.executable, str(path)], cwd=BASE, env=child_env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    elapsed = time.time() - started
    output = (proc.stdout or "") + (proc.stderr or "")

    # ASCII 마커를 먼저 보고, 없으면 한글 요약줄로 보완한다
    match = _PTS_RESULT_RE.search(output) or _RESULT_RE.search(output)
    passed = int(match.group(1)) if match else 0
    failed = int(match.group(2)) if match else 0
    skipped = len(_SKIP_RE.findall(output))

    if match is None:
        state = "crashed"
    elif failed or proc.returncode != 0:
        state = "failed"
    else:
        state = "passed"

    if verbose:
        shown = "\n".join(ln for ln in output.rstrip().splitlines()
                          if not ln.startswith("PTS_RESULT"))
        print(_safe(shown))
    elif state == "failed":
        for line in output.splitlines():
            if "[FAIL]" in line:
                print(f"      {_safe(line.strip())}")
    elif state == "crashed":
        # 실행 자체가 중단된 경우 오류 꼬리를 그대로 보여준다.
        # (이전 버전은 특정 단어가 든 줄만 골라 실제 원인을 감췄다)
        tail = [ln for ln in output.rstrip().splitlines() if ln.strip()][-10:]
        print("      --- 오류 내용 ---")
        for line in tail:
            print(f"      {_safe(line.rstrip())}")
        if "UnicodeEncodeError" in output or "codec can" in output:
            print("      * 콘솔 인코딩 문제입니다. chcp 65001 실행 후 재시도하세요.")

    return {"key": key, "title": title, "state": state, "passed": passed,
            "failed": failed, "skipped": skipped, "seconds": elapsed}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = any(a in ("-v", "--verbose") for a in sys.argv[1:])
    targets = [s for s in SUITES if not args or s[0] in args]

    if not targets:
        print(f"실행할 대상이 없습니다. 사용 가능: {', '.join(s[0] for s in SUITES)}")
        return 1

    print(BAR * 66)
    print("  포타송 설계서 작성 - 전체 검증")
    print(BAR * 66)

    results = []
    for suite in targets:
        key, filename, title, detail = suite
        print(f"\n▶ [{key}] {title}")
        print(f"   {detail}")
        outcome = run(suite, verbose)
        results.append(outcome)

        mark = {"passed": SYM["ok"], "failed": SYM["no"],
                "crashed": SYM["boom"], "missing": SYM["none"]}[outcome["state"]]
        if outcome["state"] == "missing":
            print(f"   {mark} 파일 없음 - {filename}")
        elif outcome["state"] == "crashed":
            print(f"   {mark} 실행 중단 (결과 요약을 찾지 못함)")
        else:
            skip_note = f" · SKIP {outcome['skipped']}" if outcome["skipped"] else ""
            print(f"   {mark} {outcome['passed']}건 통과 / "
                  f"{outcome['failed']}건 실패{skip_note}  ({outcome['seconds']:.1f}초)")

    total_pass = sum(r["passed"] for r in results)
    total_fail = sum(r["failed"] for r in results)
    total_skip = sum(r["skipped"] for r in results)
    broken = [r for r in results if r["state"] in ("crashed", "missing")]

    print("\n" + BAR * 66)
    print(f"  합계: {total_pass}건 통과 / {total_fail}건 실패", end="")
    print(f" / SKIP {total_skip}건" if total_skip else "")
    if broken:
        print(f"  {SYM['warn']} 실행 불가 {len(broken)}건: "
              + ", ".join(f"[{r['key']}] {r['title']}" for r in broken))
    print(BAR * 66)

    if total_fail or broken:
        print("\n실패 원인을 보려면: python run_all_tests.py -v")
        return 1
    print("\n전체 검증을 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
