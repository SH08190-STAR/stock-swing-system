---
name: safe-implement
description: CURRENT_TASK.md 범위 안에서만 구현하고 테스트를 절약형으로 실행·보고한다. 기능 구현·버그 수정 작업에 사용.
---

# /safe-implement — 범위 제한 구현

## 구현 규칙

- `docs/CURRENT_TASK.md` 기준으로만 구현한다.
- "수정 허용 파일" 밖의 파일은 수정하지 않는다.
- CURRENT_TASK에 없는 기능을 임의로 추가하지 않는다.
- DB write 금지, push 금지 (이 스킬 범위 밖).

## 테스트 절차

1. 구현 중: 관련 테스트만 실행
   `py -3.12 -m pytest tests/test_XXX.py -q`
2. 완료 시: 전체 테스트 정확히 1회
   `py -3.12 -m pytest -q > .tmp/pytest.log 2>&1`
3. 테스트 출력 전문은 `.tmp/pytest.log`에 저장하고,
   성공 시 채팅에는 요약(통과 개수)만 보고한다.

## 보고 형식 (정상 완료 시, 400자 이내)

```
[결과] 성공/실패
변경: 핵심 3~5줄
검증: 테스트·compile·서버
데이터: DB write 여부
상태: push 대기 여부
```

## 실패 시

- 최초 traceback과 마지막 관련 로그 부분만 보고한다.
- 성공 로그 전문·diff 전문을 채팅에 출력하지 않는다.
- 실행하지 않은 작업을 완료했다고 보고하지 않는다.
