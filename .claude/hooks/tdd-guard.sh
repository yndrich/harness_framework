#!/bin/bash
# TDD Guard Hook — PreToolUse[Edit|Write]  (Python / sec_extract 버전)
# 구현 .py 를 작성·수정하려 할 때, 해당 모듈의 테스트가 먼저 존재하는지 확인.
# 테스트 없이 구현 코드를 작성하려 하면 차단.
# (CLAUDE.md 의 "새 기능 구현 시 반드시 테스트를 먼저 작성(TDD)" 규칙을 강제한다.)

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# 파일 경로가 없으면 통과
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# .py 가 아니면 관심 대상 아님 — 통과 (json/md/yaml/xlsx/설정 등 전부 허용)
case "$FILE_PATH" in
  *.py) ;;
  *) exit 0 ;;
esac

BASE=$(basename "$FILE_PATH")     # 예: facts.py
NAME="${BASE%.py}"                # 예: facts
DIR=$(dirname "$FILE_PATH")

# 테스트 파일 자체 / 패키지 플러밍 / 픽스처는 테스트 불필요 — 허용
case "$BASE" in
  test_*.py|*_test.py|__init__.py|__main__.py|conftest.py|setup.py)
    exit 0
    ;;
esac

# tests/ · __tests__/ · test/ 디렉터리 안의 파일도 허용
case "$FILE_PATH" in
  tests/*|*/tests/*|*/__tests__/*|test/*|*/test/*)
    exit 0
    ;;
esac

# 프로젝트 루트 (git 우선 → CLAUDE_PROJECT_DIR → 현재 디렉터리)
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")

TEST_FOUND=false

# 1) 같은 폴더에 test_<name>.py / <name>_test.py  (예: scripts/test_execute.py)
if [ -f "${DIR}/test_${NAME}.py" ] || [ -f "${DIR}/${NAME}_test.py" ]; then
  TEST_FOUND=true
fi

# 2) 프로젝트 루트 tests/ 에 1:1 테스트 파일
if [ "$TEST_FOUND" = false ]; then
  if [ -f "${ROOT}/tests/test_${NAME}.py" ] || [ -f "${ROOT}/tests/${NAME}_test.py" ]; then
    TEST_FOUND=true
  fi
fi

# 3) 프로젝트 어디든 test_<name>.py 가 존재하면 인정
if [ "$TEST_FOUND" = false ]; then
  if find "$ROOT" -name "test_${NAME}.py" -not -path '*/__pycache__/*' 2>/dev/null | grep -q .; then
    TEST_FOUND=true
  fi
fi

# 4) (집약 테스트 대응) tests/ 안의 테스트가 이 모듈을 import/참조하면 인정.
#    이 repo 는 test_sec_extract.py 하나가 facts/normalize/excel ... 여러 모듈을 커버한다.
#    TDD 워크플로: 먼저 테스트(테스트 파일은 위에서 허용)에 `from sec_extract import <name>`
#    를 추가 → 그 다음 구현 .py 를 만들면 여기서 참조가 잡혀 통과된다.
if [ "$TEST_FOUND" = false ] && [ -d "${ROOT}/tests" ]; then
  if grep -rlwF "$NAME" "${ROOT}/tests" --include='*.py' 2>/dev/null | grep -q .; then
    TEST_FOUND=true
  fi
fi

if [ "$TEST_FOUND" = false ]; then
  cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "TDD GUARD: '${NAME}' 모듈에 대한 테스트가 없습니다. 구현보다 테스트를 먼저 작성하세요 — tests/test_${NAME}.py 를 새로 만들거나, 기존 tests/ 의 테스트에서 ${NAME} 모듈을 import 하는 케이스를 먼저 추가하면 됩니다. (CLAUDE.md: 테스트 우선 작성 규칙)"
  }
}
EOF
fi

exit 0
