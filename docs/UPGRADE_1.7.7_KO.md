# Aether EM 1.7.7 — 첨부해 주신 파일 3개로 재현한 실제 원인과 수정

새 폴더에 압축 해제 후 `SETUP_WINDOWS.cmd` → `START_WINDOWS.cmd` 실행.

`aa_coil.aedt`, `total_aa.step`, `XY.dxf` 세 파일로 세 가지 서로 다른 결함을 재현했고 전부 수정함. 각각에 대해 동일한 결함을 갖는 최소 합성 케이스로 회귀 테스트를 추가함.

---

## 1. `aa_coil.aedt` — 프로젝트는 완전히 열렸는데 화면이 비어 있던 원인

**추측이 아니라 재현된 원인**: 재료 라이브러리 조회 실패임.

- HFSS 프로젝트에는 `Polyflon copper-clad ULTEM (tm)` 처럼 **공백과 하이픈이 들어간 재료명**이 있음.
- 재료 라이브러리의 `add()`는 키를 `name.lower()`로 만들고, `get()`은 여기에 더해 공백·하이픈을 `_`로 치환했음. **두 정규화가 서로 달랐음.**
- 그래서 공백이나 하이픈이 있는 재료는 저장은 되지만 **영원히 조회되지 않음**.
- `materials.list`는 라이브러리의 모든 이름을 순회하며 각각 `get()` 하므로, 그런 이름이 **하나만 있어도 호출 전체가 예외**로 끝남.
- 그리고 이 호출은 프로젝트 열기 순서에서 **"모델 로드 완료" 와 "화면에 그리기" 사이**에 있음. 예외가 나면 그리기 단계가 실행되지 않음.

따라서 모델은 메모리에 완전히 올라와 있는데 뷰포트만 비어 있었음. 메시지 창에 남아 있던
`materials.list: "material 'polyflon copper-clad ultem (tm)' not found; available: ..."`
가 바로 그 예외임.

**수정**

- 정규화를 한 곳(`MaterialLibrary.key`)으로 통일함. `add`, `get`, `__contains__`가 같은 키를 씀.
- **프로젝트 열기를 all-or-nothing에서 벗어나게 함.** 파일을 읽는 단계만 열기를 중단시킬 수 있고, 재료·표시·import 보고서·진단 단계는 실패해도 각각 보고만 하고 **모델은 반드시 그려짐**.

**확인 결과**: `aa_coil.aedt`를 실제 브라우저에서 열어 **17개 객체가 표시됨**(나머지 12개는 Parasolid로 읽을 수 없는 것이 맞음). 3회 반복해도 매번 약 7초, 동일하게 표시됨.

## 2. `total_aa.step` — import가 끝나지 않던 원인

이 STEP 파일에는 solid 18개(가장 큰 것이 48 mm) 외에 **어떤 solid에도 속하지 않는 자유 형상**이 들어 있음. HFSS가 Spatial InterOp을 거쳐 내보낸 presentation geometry임.

측정값:

| 항목 | 값 |
| --- | --- |
| body 최대 치수 | 48.5 mm |
| 자유 곡선 최대 길이 | **36,240 mm (36 m)** |
| 자유 면 최대 면적 | **321,243,520 mm² (321 m²)** |
| 정리 대상 entity 수 | **1,995개** |

`mesh.generate`는 모델 안의 **모든** entity를 메시함. 요소 크기는 solid들의 bounding box(53 mm)로 정해지므로 2.4 mm인데, 321 m² 면을 2.4 mm로 메시하면 **1억 개 규모의 삼각형**임. 이것이 "안 끝남 / 메모리 폭증"의 정체임. 실제로 이 환경에서 5 GB를 넘겨도 끝나지 않았음.

**수정**

- 표시할 body가 실제로 사용하는 entity만 남기고 나머지는 메시 전에 제거함(이 파일에서 1,995개 제거).
- 요소 크기를 **삼각형 예산으로 역산**함. 남은 면적으로부터 필요한 크기를 계산해서 예산(기본 900,000 삼각형, `AETHER_VIEW_MAX_TRIS`로 조정)을 넘지 않게 함. 넘으면 메시 seed를 자동으로 거칠게 하고 그 사실을 메시지에 남김.
- 한 개의 이상한 면이 전체 메시를 자기 스케일로 끌어내리지 못하도록 `MeshSizeFromPoints` / `MeshSizeExtendFromBoundary` 전파를 끔.
- **import 전 파일 검사(body 목록/치수) 단계에도 같은 보호를 적용함.** 이 단계도 전체 메시를 돌리고 있었고, 실제로 여기서 먼저 멈추고 있었음.

**확인 결과**

| | 이전 | 1.7.7 |
| --- | --- | --- |
| 파일 검사(probe) | 끝나지 않음, 5 GB+ | **8.6 s** |
| import + 18개 body 표시 | 끝나지 않음 | **약 20 s, 190 MB** |

이 수정은 표시·검사용 메시에만 적용됨. **FEM 해석 메시는 물리로 결정되며 변경하지 않음.**

## 3. `XY.dxf` — 도면 전체가 거부되던 원인

`Could not create line` 오류임.

- 이 DXF의 outline은 45 mm 크기인데 그 안에 **0.1 µm(1e-7 m) 길이의 선분**이 들어 있음. layout 툴이 내보낸 양자화 노이즈임.
- OpenCASCADE는 자기 confusion tolerance(모델 단위 기준 1e-7, Aether는 미터 단위)보다 짧은 edge를 만들지 않음.
- outline 하나가 실패하면 **도면 전체 import가 실패**했음.

**수정**

- ring 정리 시 tolerance를 ring 자체 크기의 비율과 **1 µm 하한** 중 큰 값으로 잡음. PCB outline의 최소 실제 피처(측정값: 27 µm)보다 200배 작고, OCC가 거부하는 값보다 10배 큼.
- outline 하나가 그래도 만들어지지 않으면 그 하나만 건너뛰고 경고를 남김. 도면 전체를 잃지 않음.

**확인 결과**: `XY.dxf`의 outline 9개가 모두 face로 생성되고 표시됨(이전에는 import 실패).

## 4. "다음 파일을 불러올 때 느려지거나 못 불러옴"

주 원인은 위 2번(끝나지 않는 메시)이었음. 추가로 캐시 위생도 정리함.

- 문서가 바뀌면(New / Open / Close / Template) **표시 버퍼 캐시, 경계 오버레이용 배열, 브라우저에 전달한 binary blob, CAD bounds 캐시를 전부 비움.** 닫힌 프로젝트의 버퍼를 다음 프로젝트까지 들고 가지 않음.
- blob 예산을 512 MB → 192 MB로 낮춤(이제 세션 전체가 아니라 한 모델 기준의 상한임).
- tessellation 캐시 예산을 3,000,000 → 1,200,000 삼각형으로 낮춤.
- 브라우저 쪽 blob 캐시도 문서 교체 시 비움.

**확인 결과**(같은 세션에서 연속 실행, 서버 RSS):

```
aa_coil 열기 1회차   7.3 s   17개 표시   189 MB
aa_coil 열기 2회차   7.4 s   17개 표시   246 MB
aa_coil 열기 3회차   6.5 s   17개 표시   274 MB
total_aa.step import 20.1 s  35개 표시   352 MB
XY.dxf import       17.6 s  36개 표시   406 MB
JavaScript 오류 없음
```

---

## 5. 남은 제약

- `aa_coil.aedt`의 **12개 body는 여전히 표시되지 않음.** 프로젝트가 이들을 native Parasolid(.x_b)로 저장하고 있고, OpenCASCADE는 이 포맷을 읽지 못함. 이것은 포맷 문제이지 이번 버그와 무관함. HFSS에서 `Modeler ▸ Export ▸ .step`으로 내보낸 뒤 해당 객체를 선택하고 `Modeler ▸ Replace CAD Source`를 쓰면 됨. 어떤 객체가 여기에 해당하는지는 `View ▸ Display Diagnostics`에 `no geometry`로 표시됨.
- 위 시간은 이 Linux 컨테이너 기준임. Windows 실측치는 다를 수 있음.
- STEP import 20초 중 대부분은 OCC의 STEP 파싱과 body별 bounds 계산임. 표시 메시 자체는 더 이상 병목이 아님.

## 6. 검증

- 회귀 테스트 12건 신규(`tests/test_import_177.py`): 재료명 정규화 4건, 자유 entity 제거와 삼각형 예산 3건, DXF ring 정리 3건, 문서 교체 시 캐시 비움 2건.
- 브라우저 테스트 1건 추가(`tests/test_gui_lifecycle_175.py`): 읽기 이후 단계가 실패해도 모델이 화면에 남는지 확인.
- 전체 pytest 583건 통과, 실패/오류 0건 (gmsh/OCC + Playwright Chromium 설치된 Linux 컨테이너).
