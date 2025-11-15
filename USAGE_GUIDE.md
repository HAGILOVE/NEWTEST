# 사용 가이드 (Usage Guide)

## Visual Prompt Generator for Patents, Papers, and Reports

특허, 논문, 보고서 등의 기술 문서를 분석하여 시각화 프롬프트를 자동 생성하는 도구입니다.

---

## 🚀 빠른 시작 (Quick Start)

### 1. 설치 (Installation)

```bash
# 필요한 패키지 설치
pip install -r requirements.txt

# API 키 설정
export ANTHROPIC_API_KEY='your-api-key-here'
```

### 2. 기본 사용법 (Basic Usage)

#### 방법 1: 대화형 CLI 사용

```bash
python visual_prompt_generator.py
```

프롬프트에 따라 입력:
- **주제(Topic)**: 분석할 내용의 주제
- **내용(Content)**: 특허/논문/보고서의 전체 또는 일부 내용 (Ctrl+D로 입력 종료)
- **질문(Question)**: 선택사항 - 특정 질문이나 관심사항

#### 방법 2: Python 코드에서 사용

```python
from visual_prompt_generator import VisualPromptGenerator

# 초기화
generator = VisualPromptGenerator()

# 분석 실행
results = generator.analyze_content(
    topic="AI 의료 진단 시스템",
    content="이 특허는 인공지능을 활용한 조기 암 진단 시스템에 관한 것으로...",
    question="시스템 구조를 어떻게 시각화할 수 있을까요?"
)

# 결과 출력
print(results['raw_response'])

# 파일로 저장
generator.save_results(results, "output.md")
```

#### 방법 3: 파일에서 내용 읽기

```python
results = generator.generate_from_file(
    file_path="my_patent.txt",
    topic="블록체인 기반 투표 시스템",
    question="핵심 기능을 시각화하려면?"
)
```

---

## 📋 출력 형식 (Output Format)

생성되는 결과는 다음 섹션들을 포함합니다:

### 1. IDEAS AND ANALYSIS
- **Core Concepts**: 핵심 개념 분석
- **Technical Components**: 주요 기술 요소
- **Innovation and Impact**: 혁신성과 영향
- **Unique Aspects**: 차별화 요소

### 2. VISUAL STRATEGY
- **Visualization Approach**: 시각화 접근 방식
- **Visual Sequence Plan**: 시각 요소의 논리적 흐름

### 3. VISUAL PROMPTS (ENGLISH)
- 5-7개의 상세한 이미지 생성 프롬프트
- 각 프롬프트 포함 요소:
  - **Type**: 시각 자료 유형 (다이어그램, 일러스트 등)
  - **Description**: 상세한 영어 설명 (구성, 스타일, 요소, 색상, 시점)

### 4. USAGE RECOMMENDATIONS
- 생성된 시각 자료 활용 가이드

---

## 💡 예제 (Examples)

### 예제 1: AI 의료 진단 특허

```python
topic = "AI 기반 조기 암 진단 시스템"

content = """
이 특허는 다중 모달 의료 영상을 활용한 인공지능 암 조기 진단 시스템입니다.
CT, MRI, 혈액 검사 결과를 종합하여 암 위험도를 평가합니다.

주요 혁신:
1. 다중 영상 모달리티 동시 처리 딥러닝 아키텍처
2. 의심 조직 영역을 강조하는 어텐션 메커니즘
3. 유전자 마커와 환자 이력 통합 개인화 위험 평가
...
"""

results = generator.analyze_content(topic, content)
```

생성되는 시각 프롬프트 예시:
- "Medical AI system architecture diagram showing data flow..."
- "3D visualization of neural network highlighting attention mechanism..."
- "Before/after comparison infographic showing detection accuracy..."

### 예제 2: 양자 컴퓨팅 논문

```python
topic = "위상 큐비트 기반 양자 오류 정정"

content = """
마요라나 페르미온을 활용한 위상 큐비트 기반의
새로운 양자 오류 정정 방법을 제시합니다...
"""

results = generator.analyze_content(topic, content)
```

### 예제 3: 스마트 그리드 보고서

파일에서 읽기:
```python
results = generator.generate_from_file(
    "smart_grid_report.txt",
    topic="스마트 그리드 에너지 관리",
    question="시스템 아키텍처와 이점을 시각화하려면?"
)
```

---

## 🎨 생성된 프롬프트 활용 방법

생성된 영어 프롬프트는 다음 AI 이미지 생성 도구에서 사용할 수 있습니다:

1. **DALL-E 3** (OpenAI)
   ```
   ChatGPT Plus에서 직접 사용
   또는 OpenAI API 활용
   ```

2. **Midjourney**
   ```
   Discord에서 /imagine 명령어와 함께 사용
   예: /imagine [생성된 프롬프트]
   ```

3. **Stable Diffusion**
   ```
   로컬 또는 온라인 인터페이스에서 사용
   DreamStudio, Clipdrop 등
   ```

4. **Adobe Firefly**
   ```
   Adobe Creative Cloud에서 활용
   ```

---

## 🔧 고급 사용법 (Advanced Usage)

### API 키를 코드에서 직접 설정

```python
generator = VisualPromptGenerator(api_key="your-api-key")
```

### 결과를 JSON으로도 저장

```python
generator.save_results(results, "output.md")
# 자동으로 output.json도 생성됨
```

### JSON 결과 활용

```python
import json

with open("output.json", "r") as f:
    data = json.load(f)

# 섹션별로 접근
sections = data['sections']
visual_prompts = sections.get('VISUAL PROMPTS (ENGLISH)', '')
```

---

## 📝 팁과 모범 사례

### 효과적인 입력을 위한 팁:

1. **명확한 주제 설정**
   - ✅ "딥러닝 기반 자율주행차 충돌 예방 시스템"
   - ❌ "자동차"

2. **충분한 기술적 세부사항 제공**
   - 핵심 기술, 혁신 사항, 구성 요소 포함
   - 최소 200-500자 권장

3. **구체적인 질문 제시**
   - ✅ "시스템 아키텍처와 데이터 흐름을 시각화하려면?"
   - ✅ "핵심 알고리즘의 작동 원리를 설명하는 다이어그램은?"
   - ❌ "그림 만들어줘"

4. **컨텍스트 제공**
   - 대상 독자 (전문가, 일반인, 투자자)
   - 사용 목적 (발표, 논문, 특허 출원)

### 생성된 프롬프트 개선:

생성된 프롬프트를 더욱 정교하게 만들려면:
- 특정 색상 팔레트 추가
- 아트 스타일 지정 (미니멀, 상세, 사실적 등)
- 비율이나 시점 명시
- 브랜드 요소 통합

---

## 🐛 문제 해결 (Troubleshooting)

### API 키 오류
```
ERROR: ANTHROPIC_API_KEY environment variable not set
```
**해결**: `export ANTHROPIC_API_KEY='your-key'` 실행

### 입력 오류
```
ERROR: Content is required
```
**해결**: 내용을 입력한 후 새 줄에서 Ctrl+D 눌러 입력 종료

### 모듈 import 오류
```
ModuleNotFoundError: No module named 'anthropic'
```
**해결**: `pip install -r requirements.txt` 실행

---

## 📞 지원 및 피드백

문제가 발생하거나 제안사항이 있으시면:
- GitHub Issues 활용
- 상세한 오류 메시지와 입력 내용 포함

---

## 📄 라이선스

이 도구는 교육 및 연구 목적으로 자유롭게 사용할 수 있습니다.

---

**즐거운 시각화 되세요! 🎨**
