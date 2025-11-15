#!/usr/bin/env python3
"""
Example usage of Visual Prompt Generator

This script demonstrates how to use the VisualPromptGenerator class
to analyze technical content and generate visual prompts.
"""

from visual_prompt_generator import VisualPromptGenerator
import os


def example_patent_analysis():
    """Example: Analyzing a patent about AI medical diagnosis"""

    # Initialize the generator
    generator = VisualPromptGenerator()

    # Example patent content
    topic = "AI-Powered Early Cancer Detection System"

    content = """
    This patent describes an artificial intelligence system for early detection of cancer
    using multi-modal medical imaging. The system combines CT scans, MRI images, and
    blood test results to provide comprehensive cancer risk assessment.

    Key innovations:
    1. Deep learning architecture that processes multiple imaging modalities simultaneously
    2. Novel attention mechanism that highlights suspicious tissue regions
    3. Integration of genetic markers and patient history for personalized risk assessment
    4. Real-time processing capable of analyzing scans in under 2 minutes
    5. Explainable AI features that show doctors why specific regions are flagged

    The system achieved 94% sensitivity and 97% specificity in clinical trials with
    over 10,000 patients, outperforming traditional screening methods by 23%.

    Technical Architecture:
    - Input Layer: Accepts DICOM format medical images and structured patient data
    - Feature Extraction: Multi-scale convolutional neural networks for each modality
    - Fusion Layer: Cross-attention mechanism combining features from all inputs
    - Risk Assessment: Probabilistic output with confidence intervals
    - Visualization: Heat maps and 3D reconstructions of suspicious regions
    """

    question = "How can we visualize the AI system's workflow and key innovations?"

    # Generate analysis and visual prompts
    print("Generating visual prompts for cancer detection AI system...")
    print("=" * 80)

    results = generator.analyze_content(topic, content, question)

    # Display results
    print("\n" + results['raw_response'])

    # Save results
    generator.save_results(results, "example_cancer_ai_output.md")


def example_research_paper():
    """Example: Analyzing a research paper about quantum computing"""

    generator = VisualPromptGenerator()

    topic = "Quantum Error Correction using Topological Qubits"

    content = """
    This paper presents a novel approach to quantum error correction using topological
    qubits based on Majorana fermions. The method achieves fault-tolerant quantum
    computation with significantly reduced overhead compared to surface codes.

    Main contributions:
    - Theoretical framework for braiding Majorana zero modes in nanowire networks
    - Experimental demonstration of topological protection at temperatures up to 1 Kelvin
    - Error rates reduced from 10^-3 to 10^-6 compared to standard superconducting qubits
    - Scalable architecture supporting up to 1000 logical qubits

    The research opens new pathways for practical quantum computers by addressing
    one of the fundamental challenges in quantum computing: maintaining coherence
    and correcting errors in quantum states.
    """

    print("\n" + "=" * 80)
    print("Generating visual prompts for quantum computing paper...")
    print("=" * 80)

    results = generator.analyze_content(topic, content)

    print("\n" + results['raw_response'])

    generator.save_results(results, "example_quantum_output.md")


def example_from_file():
    """Example: Reading content from a file"""

    # Create a sample file
    sample_content = """
    Smart Grid Energy Management System

    This report describes an intelligent energy distribution system that optimizes
    power grid performance using real-time data analytics and predictive algorithms.

    Key Features:
    - Real-time monitoring of 10,000+ grid nodes
    - Machine learning models predicting energy demand with 96% accuracy
    - Automated load balancing and fault detection
    - Integration with renewable energy sources (solar, wind)
    - Blockchain-based peer-to-peer energy trading platform

    System Benefits:
    - 30% reduction in energy waste
    - 45% faster fault response time
    - 20% increase in renewable energy integration
    - $2M annual cost savings for pilot city
    """

    # Save to file
    with open("sample_report.txt", "w", encoding="utf-8") as f:
        f.write(sample_content)

    # Generate from file
    generator = VisualPromptGenerator()

    print("\n" + "=" * 80)
    print("Generating visual prompts from file...")
    print("=" * 80)

    results = generator.generate_from_file(
        "sample_report.txt",
        topic="Smart Grid Energy Management",
        question="How can we visualize the system architecture and benefits?"
    )

    print("\n" + results['raw_response'])

    generator.save_results(results, "example_smartgrid_output.md")


if __name__ == "__main__":
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Please set ANTHROPIC_API_KEY environment variable")
        print("Example: export ANTHROPIC_API_KEY='your-api-key-here'")
        exit(1)

    print("Visual Prompt Generator - Examples")
    print("=" * 80)
    print("\nThis will generate visual prompts for three different examples:")
    print("1. AI Medical Diagnosis Patent")
    print("2. Quantum Computing Research Paper")
    print("3. Smart Grid Report (from file)")
    print("\nNote: This will use your Anthropic API credits.")
    print("=" * 80)

    proceed = input("\nProceed with examples? (y/n): ").strip().lower()

    if proceed == 'y':
        try:
            # Run examples
            example_patent_analysis()
            print("\n" + "=" * 80 + "\n")

            example_research_paper()
            print("\n" + "=" * 80 + "\n")

            example_from_file()

            print("\n" + "=" * 80)
            print("All examples completed!")
            print("Check the generated *_output.md and *.json files for results.")
            print("=" * 80)

        except Exception as e:
            print(f"\nError: {str(e)}")
            import traceback
            traceback.print_exc()
    else:
        print("Cancelled.")
