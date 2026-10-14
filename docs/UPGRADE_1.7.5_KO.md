# Aether EM 1.7.5 — 프로젝트 닫기, 저장 확인, 진행 표시, 뷰포트 속도

새 폴더에 압축 해제 후 `SETUP_WINDOWS.cmd` → `START_WINDOWS.cmd` 실행. 대형 STEP은 `START_FAST_WINDOWS.cmd`로 실행할 수 있음.

이번 버전은 문서(프로젝트) 수명주기, 장시간 작업의 진행 표시, 3-D 뷰포트 성능 세 가지를 다룸.

---

## 1. Close Project와 저장 확인

### 추가된 것

- **File ▸ Close Project** (`Ctrl+W`). 프로젝트를 닫으면 빈 프로젝트를 대신 만들지 않고 "열린 프로젝트 없음" 상태가 됨. HFSS가 프로젝트 사이에 두는 상태와 같음. 트리에는 New / Open 두 버튼이 표시됨.
- **File ▸ Exit**. 서버 프로세스를 실제로 종료함. 이전에는 브라우저 탭만 닫혀 Python 프로세스와 포트가 남았음.
- **Save / Don't Save / Cancel 3버튼 확인창**. 저장하지 않은 변경이 버려지는 모든 경로에서 표시됨.
  - New Project
  - New from Template
  - Open Project
  - Close Project
  - Exit

이전 확인창은 `window.confirm` 기반이라 **버리기 / 취소** 두 가지뿐이었음. 즉 작업을 지키려면 취소 → 수동 저장 → 명령 재실행을 해야 했음. 이제 Save를 선택하면 저장(경로가 없으면 Save As 대화상자)이 끝난 뒤 원래 명령이 이어서 실행됨. Save As에서 사용자가 취소하면 원래 명령도 실행되지 않음.

### 프로젝트 트리 우클릭

- 프로젝트 노드: Save / Save As… / Insert Design / Close Project
- 디자인 노드: Set as Active Design / Rename Design… / Insert Design / Delete Design
- `Project ▸ Rename Design…`, `Project ▸ Delete Design` 메뉴도 추가됨. 디자인 이름 변경은 이전에 불가능했음.
- 마지막 남은 디자인은 삭제되지 않음. 프로젝트 전체를 닫는 것이 올바른 동작이므로 그렇게 안내함.

`project.close`는 디스크에 아무것도 쓰지 않음. 저장 여부는 UI가 먼저 묻고, 저장이 필요하면 `project.save`를 별도로 호출함.

---

## 2. 진행 표시

### 문제

프로젝트 열기, CAD import, 표시 버퍼 재생성은 실제 모델에서 수 초~수 분이 걸리는데 그동안 아무 표시가 없었음. 화면이 멈춘 것과 구분되지 않았음.

### 구현

서버에 진행 채널(`Progress`)을 추가함. 단계(stage), 현재 항목(detail), 처리 수/전체 수를 게시함.

중요한 점은 이 채널을 읽는 요청이 **명령을 실행하는 요청과 다른 요청**이라는 것임. 명령 실행은 세션 락을 잡고 있으므로, 같은 경로로 읽으면 명령이 끝날 때까지 아무것도 못 읽음. `/api/messages`는 락을 잡지 않고 답하므로 진행 상황이 계속 갱신됨.

브라우저는 200 ms 간격으로 이를 읽어 화면 중앙 오버레이(단계 이름 + 막대 + 현재 항목)와 하단 Progress 패널에 표시함. 전체 개수를 알 수 없는 단계는 백분율을 지어내지 않고 부정형(indeterminate) 막대로 표시함.

### 단계가 보고되는 작업

| 작업 | 보고되는 단계 |
| --- | --- |
| Open Project | 프로젝트 파일 파싱 → (aedtz면) 압축 해제 → 디자인 n/N 읽기 → 모델 트리 구성 |
| Import CAD | CAD 파일 읽기 → 형상 검사 → 모델에 body 추가 |
| 뷰포트 재생성 | 객체별 tessellation, 현재 객체 이름과 n/N |

작업이 실패하면 진행 채널이 오류 메시지와 함께 종료되고 오버레이가 사라짐.

---

## 3. 뷰포트 속도

### 원인 (1.7.4까지)

1. **tessellation 캐시가 import된 body에만 적용됨.** Box, Cylinder, Boolean, Face Operation 등은 캐시 대상이 아니어서 화면을 다시 그릴 때마다 OpenCASCADE 표면 메시를 처음부터 다시 생성했음. 뷰포트는 편집할 때마다 다시 그려지므로, 객체 하나를 옮기면 나머지 전부가 다시 계산되었음.
2. **경계·포트 오버레이가 모델 전체를 한 번 더 tessellate 했음.** 다시 그릴 때마다 전체 삼각형을 두 번 처리했음.
3. **면(face) 메타데이터 계산이 face 수 × 삼각형 수.** face마다 `face_of == k` 마스크를 전체 삼각형에 적용하는 Python 루프였음. face가 수천 개인 STEP body가 정확히 이 최악 경우임.
4. **정점 배열을 JSON 숫자로 전송.** 좌표마다 `round(float(x), 9)` Python 루프 + JSON 텍스트. float 데이터의 3배 크기이고, 브라우저에서 파싱 비용이 한 번 더 듦.
5. **브라우저가 매번 모든 객체의 GPU 버퍼·선택용 BVH·면 외곽선을 다시 만들었음.**

### 변경

1. 모든 shape에 대해 내용 기반(content-addressed) tessellation 캐시를 적용함. 키는 shape 트리의 완전한 직렬화 해시이며, import 파일은 수정 시각/크기를 포함함. 객체 **이름은 키에서 제외**함 — 이름 변경은 형상 변경이 아니므로 다시 계산하지 않음.
2. 경계·포트 오버레이는 캐시된 표시 삼각형을 재사용함.
3. face 메타데이터, face 외곽선 추출, face 군집화를 배열 연산(`bincount`, 세그먼트 reduce, sparse connected components)으로 다시 씀. 군집화 결과가 기존 flood fill과 동일한 분할을 내는지 회귀 테스트로 확인함(Box 6면, 닫힌 Cylinder 3면, 원뿔 2면, 구 1면).
4. 각 객체에 형상 digest를 부여함. 브라우저는 자신이 가진 digest를 함께 보내고, 서버는 바뀌지 않은 객체를 `unchanged`로만 응답함. 색·투명도·표시 여부는 값이 싸므로 항상 함께 보냄.
5. 정점 배열은 JSON 대신 float32/int32 blob으로 별도 요청에서 전송함. blob은 내용 주소이므로 같은 배열은 한 번만 전송·캐시됨.
6. 브라우저는 `unchanged` 객체의 GPU 버퍼와 BVH를 그대로 재사용하고, 실제로 바뀐 객체만 다시 만듦.

### 측정값

동일 장면(Box 12개 + Cylinder 12개, 표시 삼각형 45,790개, PEC outer 경계), 동일 컨테이너에서 1.7.4와 1.7.5를 같은 스크립트로 측정함.

| 항목 | 1.7.4 | 1.7.5 |
| --- | --- | --- |
| 최초 표시 (geometry + assignments) | 3,315 ms | 1,226 ms |
| 변경 없는 재표시 | 3,313 ms | 22 ms |
| 객체 하나를 옮긴 뒤 재표시 | 3,328 ms | 87 ms |
| geometry 응답 크기 (전체) | 9.28 MB | 0.46 MB (binary) |
| geometry 응답 크기 (1개만 변경) | 9.28 MB | 0.026 MB |

즉 편집 반복 시의 서버 측 비용이 약 38배, 카메라 조작 등 변경 없는 재표시가 약 150배 줄었음. 최초 로딩은 약 2.7배임.

### 호환성

`view.geometry`의 기본 응답 형식은 바뀌지 않았음. `have`(가진 digest)와 `binary`(blob 전송)는 모두 선택적 인자이며, 브라우저만 사용함. 스크립트·기존 테스트는 이전과 동일한 전체 배열을 받음.

---

## 4. 그 밖의 수정

- **Export Solution Data**에 파일 탐색 버튼을 추가하고 절대 경로로 해석함. 이전에는 상대 경로가 서버 프로세스의 시작 디렉터리에 저장되어 사용자가 찾을 수 없었음. 빈 경로는 거부함.
- 실패해서 되돌려진 명령이 디자인의 모든 body를 "같지만 다른" 복사본으로 바꾸던 문제를 고침. 아무것도 건드리지 않은 객체는 원래 객체 그대로 남음. (1.7.4에서 실패하던 회귀 테스트 1건이 이것임.)
- `File ▸ Exit`, `Ctrl+W`(Close), `Ctrl+Shift+S`(Save As) 단축키.
- 프로젝트가 닫힌 상태에서 Save/Close/Export 메뉴 항목이 비활성화됨.

---

## 5. 검증 범위와 한계

- 전체 pytest 552건 통과, 실패/오류 0건 (Linux 컨테이너, gmsh/OCC + Playwright Chromium 설치 상태). 1.7.4에서 실패하던 `test_a_face_operation_that_cannot_build_leaves_the_body_alone` 1건도 이번에 함께 고침.
- 이번 변경에 대한 회귀 테스트를 새로 추가함.
  - `tests/test_release_175.py` 26건: 프로젝트 닫기, 진행 채널, digest 기반 차분 전송, binary 전송, 캐시 동작, face 군집화 동등성, 되돌림 시 객체 동일성.
  - `tests/test_gui_lifecycle_175.py` 14건: 실제 브라우저에서 저장 확인창의 세 가지 답(Cancel / Don't Save / Save), 닫힌 뒤의 화면 상태, Exit 확인, 진행 오버레이 표시, 변경된 객체만 재생성되는지, binary 전송 경로.
- 기존 브라우저 테스트 두 건은 이번 변경에 맞춰 수정함. 전체 메뉴 클릭 테스트는 Close Project·Exit을 제외함(그 둘은 실행되면 테스트 대상 세션 자체를 없앰). `test_cancel_unsaved_new_keeps_project`는 브라우저 confirm 대신 새 확인창을 조작하도록 바꿈.
- 위 성능 수치는 이 컨테이너에서 합성 장면으로 측정한 **서버 측** 시간임. 브라우저 GPU 업로드 시간, Windows에서의 FPS, 실제 사용자 STEP 파일의 로딩 시간은 측정하지 못함.
- 매우 큰 STEP의 초기 CAD 파싱과 표시 메시 생성 비용 자체는 그대로 남아 있음. 캐시는 **두 번째 이후**를 줄이는 것이지 첫 파싱을 없애지 않음. 따라서 어떤 용량이든 즉시 열린다고 보장하지 않음.
- 저장 확인창과 Close 동작은 실제 브라우저 자동화 테스트가 아니라 서버 측 명령 단위로 검증함. UI 동작은 수동 확인이 필요함.
- HFSS/AEDT 호환 범위, Parasolid body 미지원, PML 제한은 1.7.3·1.7.4 안내와 동일함. 이번 버전에서 바뀐 것이 없음.
- 계속 느린 파일이 있으면 원본 STEP/AEDT 파일, 용량, 대략적인 부품 수, 로딩 시간, RAM/GPU 정보를 함께 주면 추가 프로파일링이 가능함.
