# Visual Prompt Generator 🎨

**Generate detailed visual prompts from patents, papers, and reports**

Transform complex technical content into compelling visual narratives with AI-powered analysis and prompt generation.

---

## 📖 Overview

This tool analyzes technical documents (patents, academic papers, research reports) and automatically generates:

1. **📊 Ideas & Analysis** - Deep technical understanding of core concepts
2. **🎯 Visual Strategy** - Intelligent planning of visualization approaches
3. **🖼️ Multiple Detailed Visual Prompts** - Ready-to-use prompts in English for AI image generators (DALL-E, Midjourney, Stable Diffusion, etc.)

Perfect for researchers, patent attorneys, technical writers, and anyone who needs to visualize complex technical concepts.

---

## ✨ Features

- 🤖 **AI-Powered Analysis** - Uses Claude Sonnet 4.5 for intelligent content understanding
- 🎨 **Multi-Modal Visualization** - Generates prompts for diagrams, flowcharts, infographics, technical illustrations
- 📝 **Detailed Prompts** - Each prompt includes composition, style, elements, colors, and perspective
- 🌍 **English Output** - All visual prompts in English for universal AI image generator compatibility
- 💾 **Multiple Output Formats** - Saves as Markdown and JSON for easy integration
- 🔄 **Flexible Input** - CLI interface, Python API, or file-based input

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/HAGILOVE/NEWTEST.git
cd NEWTEST

# Install dependencies
pip install -r requirements.txt

# Set up your Anthropic API key
export ANTHROPIC_API_KEY='your-api-key-here'
```

### Basic Usage

#### Option 1: Interactive CLI

```bash
python visual_prompt_generator.py
```

Follow the prompts to enter:
- **Topic**: The main subject of your document
- **Content**: Paste your patent/paper/report content (press Ctrl+D when done)
- **Question** (optional): Specific visualization questions

#### Option 2: Python API

```python
from visual_prompt_generator import VisualPromptGenerator

# Initialize
generator = VisualPromptGenerator()

# Analyze content
results = generator.analyze_content(
    topic="AI-Powered Cancer Detection System",
    content="This patent describes an innovative approach to...",
    question="How to visualize the system architecture?"
)

# View results
print(results['raw_response'])

# Save to file
generator.save_results(results, "output.md")
```

#### Option 3: From File

```python
results = generator.generate_from_file(
    file_path="my_patent.txt",
    topic="Blockchain Voting System",
    question="How to visualize the security features?"
)
```

---

## 📚 Examples

### Example 1: Medical AI Patent

**Input:**
```python
topic = "AI-Powered Early Cancer Detection System"
content = """
This patent describes an artificial intelligence system for early detection
of cancer using multi-modal medical imaging. The system combines CT scans,
MRI images, and blood test results...
"""
```

**Output includes:**
- Core concept analysis
- Technical component breakdown
- 5-7 detailed visual prompts such as:
  - "Technical diagram showing multi-modal AI architecture with data flow from CT/MRI scanners through neural networks to diagnosis output, isometric view, clean medical color palette..."
  - "3D visualization of deep learning attention mechanism highlighting suspicious tissue regions, volumetric rendering style..."

### Example 2: Quantum Computing Paper

Run the examples:
```bash
python example_usage.py
```

This generates visual prompts for:
1. AI Medical Diagnosis Patent
2. Quantum Computing Research Paper
3. Smart Grid Energy Report

---

## 📋 Output Structure

### 1. IDEAS AND ANALYSIS
- **Core Concepts**: Main ideas and innovations
- **Technical Components**: Key elements and relationships
- **Innovation and Impact**: Significance and applications
- **Unique Aspects**: Differentiating factors

### 2. VISUAL STRATEGY
- **Visualization Approach**: How visuals support understanding
- **Visual Sequence Plan**: Logical flow of visual elements

### 3. VISUAL PROMPTS (ENGLISH)
5-7 detailed prompts, each including:
- **Type**: Diagram, illustration, flowchart, infographic, etc.
- **Description**: Highly detailed English prompt with:
  - Composition and layout
  - Visual style and rendering
  - Key elements and components
  - Color palette and mood
  - Perspective and viewing angle

### 4. USAGE RECOMMENDATIONS
Guidance on using the generated visuals together

---

## 🎨 Using Generated Prompts

The English prompts work with popular AI image generators:

### DALL-E 3
```
Use directly in ChatGPT Plus or via OpenAI API
```

### Midjourney
```
/imagine [paste generated prompt]
```

### Stable Diffusion
```
Use in DreamStudio, Automatic1111, or ComfyUI
```

### Adobe Firefly
```
Use in Adobe Creative Cloud applications
```

---

## 🔧 Configuration

### API Key Setup

**Linux/Mac:**
```bash
export ANTHROPIC_API_KEY='your-api-key'
```

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY='your-api-key'
```

**In Python:**
```python
generator = VisualPromptGenerator(api_key="your-api-key")
```

### Customization

Modify the prompt template in `visual_prompt_generator.py` to:
- Adjust the number of visual prompts (default: 5-7)
- Specify preferred visual styles
- Target specific image generators
- Add domain-specific requirements

---

## 📖 Documentation

- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Detailed usage guide (한국어 포함)
- **[example_usage.py](example_usage.py)** - Code examples

---

## 💡 Tips for Best Results

### Input Best Practices

1. **Clear Topic**
   - ✅ "Deep Learning-Based Autonomous Vehicle Collision Prevention"
   - ❌ "Car stuff"

2. **Sufficient Detail**
   - Include key innovations, technical components, and architecture
   - Minimum 200-500 words recommended

3. **Specific Questions**
   - ✅ "How to visualize the data flow and processing pipeline?"
   - ✅ "What diagrams would explain the algorithm to investors?"
   - ❌ "Make pictures"

4. **Provide Context**
   - Target audience (experts, general public, investors)
   - Use case (presentation, paper, patent filing)

### Enhancing Generated Prompts

Fine-tune prompts by adding:
- Specific color palettes
- Art style preferences (minimal, detailed, photorealistic)
- Aspect ratios or dimensions
- Brand elements or guidelines

---

## 🛠️ Technical Stack

- **Python 3.8+**
- **Anthropic Claude API** - Sonnet 4.5 model
- **anthropic** Python SDK

---

## 📄 Project Structure

```
NEWTEST/
├── visual_prompt_generator.py  # Main application
├── example_usage.py            # Usage examples
├── requirements.txt            # Dependencies
├── README.md                   # This file
└── USAGE_GUIDE.md             # Detailed guide (한국어)
```

---

## 🐛 Troubleshooting

### API Key Error
```
ERROR: ANTHROPIC_API_KEY environment variable not set
```
**Solution:** Set the environment variable with your API key

### Module Not Found
```
ModuleNotFoundError: No module named 'anthropic'
```
**Solution:** Run `pip install -r requirements.txt`

### Input Issues
Make sure to press **Ctrl+D** (Linux/Mac) or **Ctrl+Z then Enter** (Windows) after pasting content

---

## 🤝 Contributing

Contributions welcome! Areas for improvement:
- Additional output formats (PDF, HTML)
- Support for more languages
- Integration with image generation APIs
- Web interface
- Batch processing

---

## 📝 License

This project is provided for educational and research purposes.

---

## 🙏 Acknowledgments

- Powered by Anthropic Claude Sonnet 4.5
- Inspired by the need to visualize complex technical concepts
- Built for researchers, engineers, and technical communicators

---

## 📧 Contact

For issues, questions, or suggestions:
- Open a GitHub Issue
- Include detailed error messages and input examples

---

**Happy Visualizing! 🎨✨**

---

## Example Output Preview

```markdown
# VISUAL PROMPTS (ENGLISH)

## Prompt 1: System Architecture Overview
**Type:** Technical Diagram
**Description:**
Isometric technical diagram showing AI medical diagnosis system architecture.
Multiple input streams (CT scanner, MRI machine, blood test analyzer) converging
into a central processing unit with layered neural network visualization. Clean,
modern medical blue and white color palette. Show data flow with animated-style
arrows. Include labels for each component. Professional medical technology style
with subtle gradients and depth.

## Prompt 2: Neural Network Attention Mechanism
**Type:** 3D Visualization
**Description:**
Three-dimensional volumetric rendering of a deep learning attention mechanism
analyzing medical scan. Show transparent layers of the neural network with
highlighted attention weights in warm colors (red, orange) focusing on suspicious
tissue regions. Cool blue background representing normal tissue. Cross-sectional
view with visible internal structure. Futuristic medical visualization style...
```

[See example_usage.py for complete examples]
