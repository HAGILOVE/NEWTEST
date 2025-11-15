#!/usr/bin/env python3
"""
Visual Prompt Generator for Patents, Papers, and Reports

This tool analyzes technical content (patents, papers, reports) and generates:
1. Ideas and detailed explanations
2. Multiple detailed visual prompts in English for image generation
"""

import anthropic
import os
import sys
import json
from typing import List, Dict


class VisualPromptGenerator:
    """Generates visual prompts for technical content visualization"""

    def __init__(self, api_key: str = None):
        """
        Initialize the generator with Anthropic API key

        Args:
            api_key: Anthropic API key (if not provided, reads from ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key is required. "
                "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def analyze_content(self, topic: str, content: str, question: str = None) -> Dict:
        """
        Analyze the technical content and generate ideas, explanations, and visual prompts

        Args:
            topic: The main topic (e.g., "AI-based Medical Diagnosis System")
            content: Detailed content of the patent/paper/report
            question: Optional specific question about the content

        Returns:
            Dictionary with ideas, explanations, and visual prompts
        """

        # Construct the analysis prompt
        analysis_prompt = self._build_analysis_prompt(topic, content, question)

        # Call Claude API
        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            temperature=0.7,
            messages=[
                {
                    "role": "user",
                    "content": analysis_prompt
                }
            ]
        )

        # Parse the response
        result = self._parse_response(response.content[0].text)
        return result

    def _build_analysis_prompt(self, topic: str, content: str, question: str = None) -> str:
        """Build the prompt for content analysis"""

        prompt = f"""You are an expert in technical communication and visual storytelling. Your task is to analyze technical content (patents, papers, reports) and create comprehensive visual narratives.

**INPUT:**
Topic: {topic}

Content:
{content}
"""

        if question:
            prompt += f"\nSpecific Question: {question}\n"

        prompt += """

**YOUR TASK:**

1. **Generate Ideas and Detailed Explanation:**
   - Analyze the core concepts and innovations
   - Identify key technical components and their relationships
   - Explain the significance and potential impact
   - Highlight unique aspects and differentiators

2. **Determine Visual Strategy:**
   - Identify which aspects would benefit most from visualization
   - Determine the best visual approaches (diagrams, flowcharts, infographics, technical illustrations, etc.)
   - Plan a sequence of visuals that tell a coherent story

3. **Generate Multiple Detailed Visual Prompts in English:**
   - Create 5-7 distinct visual prompts
   - Each prompt should be highly detailed and specific
   - Include: composition, style, key elements, colors, perspective, mood
   - Ensure prompts are suitable for AI image generation (DALL-E, Midjourney, Stable Diffusion)
   - Make prompts technically accurate while visually engaging

**OUTPUT FORMAT (return as structured text):**

# IDEAS AND ANALYSIS

## Core Concepts
[Detailed explanation of main ideas]

## Technical Components
[Key elements and their relationships]

## Innovation and Impact
[Significance and potential applications]

## Unique Aspects
[Differentiating factors]

---

# VISUAL STRATEGY

## Visualization Approach
[Explanation of how visuals will support understanding]

## Visual Sequence Plan
[Logical flow of visual elements]

---

# VISUAL PROMPTS (ENGLISH)

## Prompt 1: [Title/Purpose]
**Type:** [e.g., Technical Diagram, Conceptual Illustration, Flowchart]
**Description:**
[Highly detailed prompt in English, 3-5 sentences, including composition, style, elements, colors, perspective]

## Prompt 2: [Title/Purpose]
**Type:** [Visual type]
**Description:**
[Detailed prompt]

[Continue for 5-7 prompts]

---

# USAGE RECOMMENDATIONS

[Brief guidance on how to use these visuals together]

Please provide a comprehensive, detailed response that would enable someone to fully understand and visualize this technical content."""

        return prompt

    def _parse_response(self, response_text: str) -> Dict:
        """Parse the Claude response into structured data"""

        return {
            "raw_response": response_text,
            "sections": self._extract_sections(response_text)
        }

    def _extract_sections(self, text: str) -> Dict:
        """Extract different sections from the response"""

        sections = {}
        current_section = None
        current_content = []

        for line in text.split('\n'):
            if line.startswith('# '):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = line[2:].strip()
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    def generate_from_file(self, file_path: str, topic: str = None, question: str = None) -> Dict:
        """
        Generate visual prompts from a file containing technical content

        Args:
            file_path: Path to the file containing the content
            topic: Optional topic (if not provided, will be extracted from content)
            question: Optional specific question

        Returns:
            Dictionary with analysis and visual prompts
        """

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not topic:
            topic = "Technical Content Analysis"

        return self.analyze_content(topic, content, question)

    def save_results(self, results: Dict, output_file: str):
        """
        Save the results to a file

        Args:
            results: The analysis results
            output_file: Path to the output file
        """

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(results['raw_response'])

        # Also save as JSON for programmatic access
        json_file = output_file.replace('.txt', '.json').replace('.md', '.json')
        if not json_file.endswith('.json'):
            json_file += '.json'

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Results saved to:")
        print(f"  - Text: {output_file}")
        print(f"  - JSON: {json_file}")


def main():
    """Main CLI interface"""

    print("=" * 80)
    print("Visual Prompt Generator for Patents, Papers, and Reports")
    print("=" * 80)
    print()

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("Please set it with your Anthropic API key:")
        print("  export ANTHROPIC_API_KEY='your-api-key-here'")
        sys.exit(1)

    # Initialize generator
    generator = VisualPromptGenerator()

    # Get input from user
    print("Please provide the following information:\n")

    topic = input("Topic (e.g., 'AI Medical Diagnosis System'): ").strip()
    if not topic:
        print("ERROR: Topic is required.")
        sys.exit(1)

    print("\nContent (paste your patent/paper/report content, then press Ctrl+D on a new line):")
    print("-" * 80)
    content_lines = []
    try:
        while True:
            line = input()
            content_lines.append(line)
    except EOFError:
        pass

    content = '\n'.join(content_lines).strip()
    if not content:
        print("\nERROR: Content is required.")
        sys.exit(1)

    print("\n" + "-" * 80)
    question = input("\nOptional question (press Enter to skip): ").strip()

    # Generate analysis and visual prompts
    print("\n" + "=" * 80)
    print("Analyzing content and generating visual prompts...")
    print("=" * 80 + "\n")

    try:
        results = generator.analyze_content(topic, content, question if question else None)

        # Display results
        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80 + "\n")
        print(results['raw_response'])

        # Ask if user wants to save
        print("\n" + "=" * 80)
        save = input("\nSave results to file? (y/n): ").strip().lower()
        if save == 'y':
            output_file = input("Output filename (default: output.md): ").strip()
            if not output_file:
                output_file = "output.md"

            generator.save_results(results, output_file)

        print("\n" + "=" * 80)
        print("Done!")
        print("=" * 80)

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
