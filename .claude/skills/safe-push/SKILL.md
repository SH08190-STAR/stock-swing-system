---
name: safe-push
description: 승인된 커밋을 안전 점검 후 push한다. 사용자가 push를 승인했을 때만 사용.
---

# /safe-push — 승인 후 push 절차

## 실행 조건

- 사용자 메시지 또는 `docs/CURRENT_TASK.md`에 push 승인이
  **명시된 경우에만** 실행한다. 승인이 없으면 즉시 중단하고 보고한다.

## 절차

1. `git status` — 예상 파일만 변경됐는지 확인
2. `git diff --stat` — 변경 규모 확인 (전문 diff는 채팅에 출력하지 않음)
3. 예상 밖 파일이 포함돼 있으면 중단하고 보고
4. secret 검사: 스테이징 대상에 `.env`, API key, token, secret,
   password 패턴이 없는지 확인
5. 필요한 경우 compile 검사:
   `py -3.12 -m py_compile <변경된 .py 파일>`
6. 전체 테스트 정확히 1회:
   `py -3.12 -m pytest -q > .tmp/pytest.log 2>&1`
   실패 시 push 중단
7. **지정된 파일만** `git add` (`git add -A` 금지)
8. 지정된 commit message로 커밋
9. `git branch --show-current`로 현재 브랜치 확인 후 push

## 금지

- DB 및 데이터 파이프라인 실행 금지
- 승인되지 않은 파일 add 금지
- 테스트 실패 상태에서 push 금지

## 보고

push 후 commit hash와 성공 여부만 간결하게 보고한다.
