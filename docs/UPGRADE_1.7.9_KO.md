# Aether EM 1.7.9 — import 오류 정리(PML 제거), mesh·boundary·port 동작

새 폴더에 압축 해제 후 `SETUP_WINDOWS.cmd` → `START_WINDOWS.cmd` 실행.

첨부해 주신 `aetherimportstatus.csv`의 51줄을 전부 원인별로 분류해서 처리했고,
말씀하신 나머지 항목(포트 마우스 지정, wave port, generate mesh, boundary 설정,
시뮬레이션 세팅)도 실제로 동작하도록 수정함. 아래 수치는 첨부해 주신
`aa_coil.aedt`로 직접 측정한 값임.

| 항목 | 이전 | 현재 |
| --- | --- | --- |
| unresolved import 항목 | 30 | **12** |
| PML 재료 오류 | 15 | **0** |
| boundary | 0 | **1 (Radiation)** |
| 해석 영역(Region) | 없음 | **재구성됨** |
| `Setup1` 검증 | basis order 오류 | **통과** |
| Generate Mesh | `CadImportError`로 중단 | **68,981 tet / 6초** |

---

## 1. PML 관련 항목 제거 — 원래 정보만 들어옴

HFSS의 PML은 재료가 아니라 **형상**임. `PML_*` box·wedge 15개, 방향별
`PMLGroup*` 재료, 각 외곽면의 `PML_radiation*` 경계가 한 세트로 만들어짐.
이것들은 사용자가 그린 모델이 아니고, 좌표 늘림(stretched coordinate) 흡수체는
본 솔버가 푸는 대상도 아님. 따라서 **형상 생성 이전 단계에서 전부 제외**함.

- `PML_*` 이름 또는 `PML*` 재료를 가진 part → import 대상에서 제외 (형상 계산 전에
  버리므로 import 속도도 빨라짐)
- `PMLGroup*` 재료 → 재료 라이브러리에 등록하지 않음
- `PML_radiation*` 경계, PML body에만 붙은 경계·포트 → 제외

### 다만 "그냥 지우기"만 하면 안 됨

PML은 개방(open) 경계임. 지우기만 하면 모델이 조용히 **닫힌 경계**가 되어
해가 완전히 달라짐. 그래서 PML이 대신하고 있던 조건을 **외곽면 Radiation
경계(`Radiation1`)로 복원**함. 다만 Radiation은 1차 흡수 경계이므로, PML보다
반사가 크고 **공기 여유(clearance) λ/4 이상**이 필요함 — 이 내용은 import 시
메시지 창에 함께 표시됨.

## 2. 공기 영역(Region) 재구성 — 해석 영역이 생김

`Region`은 HFSS에서 "모델 bounding box + 각 면 padding"으로 저장됨.
기존에는 지원하지 않는 part로 처리되어 빠졌고, 그 결과 모델에 금속만 남아
**풀 수 있는 부피가 없는 상태**였음. 이것이 mesh와 boundary가 동작하지 않던
근본 원인 중 하나임.

이제 `RegionParameters`의 `+X/-X/+Y/-Y/+Z/-Z` padding을 읽어 재구성함.
`Absolute Offset`(예: `30mm`)과 `Percentage Offset`(모델 치수 대비 %)을 모두 지원하고,
사용자가 이후 손으로 sweep 한 면(`SweepFaceAlongNormal`)이 있으면 그만큼 더 키움.
재료는 프로젝트에 기록된 값(보통 vacuum), `SolveInside=true`로 들어옴.

> 참고: Region은 다른 body들의 extent를 기준으로 만들어지므로, 형상이 하나도
> 읽히지 않은 프로젝트에서는 만들 수 없음. 그 경우에는 이유를 그대로 표시함.

## 3. Setup 검증 오류 (`basis order must be 1 or 2`)

HFSS는 mixed order를 `BasisOrder=0`, zeroth order를 `-1`로 저장함.
이 값이 그대로 들어와서, 사용자가 건드린 적도 없는 setup이 검증에서 실패하고 있었음.
지원 차수(1차)로 보정하고 보정 사실을 리포트에 남김.

## 4. Generate Mesh — 동작함

**원인**: ACIS(`.sab`)·Parasolid(`.x_b`) 첨부로 저장된 body는 어떤 오픈 커널로도
복원할 수 없음. 그런 body가 **하나라도** 있으면 `Assembly.build`가 예외를 던져
**전체 mesh 생성이 중단**되고 있었음. 이것이 "generate mesh 기능이 동작을 하지 않음"의
직접 원인임.

**수정**:

- 만들 수 없는 body는 assembly에서 **제외하고 계속 진행**함
- 어떤 body가 왜 빠졌는지 메시지 창에 명시 (`Modeler ▸ Repair Bodies` 안내 포함)
- body가 하나도 만들어지지 않는 경우에만 중단하고, 그때도 다음 행동을 알려주는 문장으로 중단함

추가로 **초기 mesh가 끝나지 않는 문제**도 함께 고침. 도체의 굴절률은 수천 단위라,
그 값이 요소 크기를 정하면 60 mm 보드에 80 nm 요소를 요구하게 됨(사실상 무한 대기).

- `solve_inside=False`·PEC body는 요소 크기 결정에서 제외
- 크기 결정에 쓰이는 굴절률 상한(30)
- 요소 수 예산(200만) 역산으로 크기를 보정하고, 보정했다는 사실을 로그로 남김

## 5. Modeler ▸ Repair Bodies — STEP 하나로 한 번에 복구

읽을 수 없는 body가 40개면 `Replace CAD Source`를 40번 해야 했음.
이제 STEP 파일을 한 번만 읽고, 이름으로 자동 매칭한 표를 보여준 뒤 적용함.

- 파일에 이름이 없어도(`SOLID`만 있는 STEP) **각 body의 실제 치수(mm)**를 함께
  표시하므로 크기로 식별 가능
- 매칭을 고치고 나서 적용되며, 적용 전에는 모델이 바뀌지 않음
- body 하나 단위 교체가 필요하면 기존 `Replace CAD Source`도 그대로 있음

## 6. 포트를 마우스로 지정 — signal, gnd

`Simulation ▸ Excitations ▸ Lumped Port (pick)` 또는 뷰포트 우클릭 메뉴.

1. **signal 도체 면**을 클릭 → 자동으로 ground 단계로 넘어감
2. **gnd 면**을 클릭
3. 임피던스 확인 후 **Apply**

- 두 면 사이 간격을 잇는 **sheet가 자동 생성**됨. 폭은 두 면 중 좁은 쪽 기준
- **integration line은 gnd → signal** 방향으로 생성됨. 이 방향이 V의 부호,
  즉 포트 임피던스의 부호를 결정하므로 임의로 두지 않음
- Ctrl+클릭으로 한쪽에 면을 여러 개 추가 가능. `S`/`G`로 signal/ground 행 전환,
  Esc 취소, Enter 적용
- 순서는 상관없음 — 먼저 gnd를 고르고 싶으면 `G`를 눌러 ground 행을 켜고 클릭하면 됨

**Wave Port (pick)** 도 같은 방식임. 클릭한 단면에 포트를 지정하고,
reference(gnd) 면을 추가로 클릭하면 **integration line**이 함께 만들어짐 —
coax·microstrip 같은 TEM 선로에서 modal 임피던스를 V²/2P 정의로 바꾸는 데 필요함.

기존 대화상자 방식(`Wave Port…`, `Lumped Port…`)도 그대로 남아 있음.

## 7. Boundary 설정이 "동작하지 않던" 부분

boundary 지정 자체는 정상이었으나, 위 1·2·4항 때문에 **지정할 면이 없는 모델**이
만들어지고 있었음(PML만 남고, 해석 영역이 없고, mesh가 안 만들어짐).
그 세 가지를 고친 것이 실질적인 수정임. 여기에 더해:

- boundary·port를 지정하면 **실제로 덮은 면 삼각형 수**를 함께 보고함
- **아무 면에도 닿지 않으면 경고**함. 트리에는 있는데 모델에는 없는 경계는
  해석이 조용히 틀리는 가장 흔한 원인임
- 형상이 없는 body는 지정 대상 계산에서 제외됨

## 8. 그 외

- Generate Mesh를 형상 없는 design에서 실행하면 이유를 말함
- setup 없이 mesh를 만들면 1 GHz 기준으로 시드했다고 알림
- import 리포트에서 PML 관련 잡음이 사라져, 남은 12건이 **실제로 확인이 필요한 항목**만
  가리키게 됨 (대부분 ACIS body — 5항으로 복구 가능)

---

## 남아 있는 제약 (숨기지 않고 적음)

`aa_coil.aedt`의 실제 부품 12개는 ACIS 바이너리(`.sab`)로만 저장되어 있음.
ACIS는 Spatial사의 비공개 포맷이고 OpenCASCADE·gmsh 어느 쪽도 읽지 못함.
따라서 **이 body들의 형상은 원리적으로 복원할 수 없음**. 해결 경로는 하나임:

> HFSS에서 `Modeler ▸ Export ▸ .step`으로 내보낸 뒤,
> Aether에서 `Modeler ▸ Repair Bodies`로 한 번에 연결

첨부해 주신 `total_aa.step`이 정확히 그 파일로 보임 (solid 18개).
연결하면 mesh·boundary·port가 모두 실제 형상 위에서 동작함.

## 검증

- 파이썬 테스트 537건 통과 (신규 20건: PML 제거, Region 재구성, basis order,
  mesh skip, 요소 크기 상한, 포트 생성, 빈 지정 경고)
- 브라우저 테스트 신규 7건: 포트 pick 흐름(면 클릭 → 단계 전환 → Apply → sheet 생성)
- `aa_coil.aedt` 3개 design 모두 열림, mesh 생성 확인
