"""
Thesis Generator: A helper script to complete and improve draft investment theses.

Usage:
    python thesis-generator.py path/to/draft-thesis.md

The script will:
1. Read your draft thesis (can be incomplete, just an idea, or partially written)
2. Load the completed thesis examples for formatting reference
3. Call OpenAI (with web search) to research, refine, and complete your thesis
4. Save the original draft as <file>.bak and overwrite the file with the improved thesis
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from openai_support import create_openai_client, create_response_text
from utils import load_environment, report_unexpected_error, write_text_atomic

# Templates and drafts are not finished theses, so they are not used as examples.
NON_EXAMPLE_FILES = {"general-thesis.md"}
DRAFT_SUFFIX = "-draft.md"


class ThesisGeneratorError(Exception):
    """Raised when thesis generation with OpenAI cannot be completed."""


class ThesisGenerator:
    """Generates and refines investment theses using OpenAI."""

    def __init__(self, model: str | None = None):
        self.client = create_openai_client(ThesisGeneratorError)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.root_dir = Path(__file__).resolve().parent
        self.examples_dir = self.root_dir / "thesis-examples"

    def load_examples(self) -> dict[str, str]:
        """Load completed thesis examples for formatting reference."""
        examples = {}
        if self.examples_dir.exists():
            for md_file in sorted(self.examples_dir.glob("*.md")):
                if md_file.name in NON_EXAMPLE_FILES or md_file.name.endswith(DRAFT_SUFFIX):
                    continue
                examples[md_file.name] = md_file.read_text(encoding="utf-8")
        return examples

    def generate(self, draft_text: str) -> str:
        """
        Generate a completed thesis from a draft using OpenAI.
        
        Args:
            draft_text: The draft thesis content (can be incomplete)
            
        Returns:
            A refined, completed thesis in proper markdown format
        """
        examples = self.load_examples()
        examples_context = "\n\n".join(
            f"## Example: {name}\n{content}" for name, content in examples.items()
        )

        system_prompt = (
            "You are an expert investment thesis writer. You help investors develop "
            "thorough, well-structured investment theses. You may research companies online "
            "to find relevant information, industry trends, competitive positioning, and "
            "financial metrics. Your goal is to produce a comprehensive, actionable thesis "
            "that clearly articulates the investment case and associated risks."
        )

        user_prompt = (
            "You are helping an investor complete their investment thesis. Here are some "
            "example well-formatted theses to use as a template:\n\n"
            f"{examples_context}\n\n"
            "---\n\n"
            "Here is the investor's draft thesis (may be incomplete, just an idea, or "
            "partially written):\n\n"
            f"{draft_text}\n\n"
            "---\n\n"
            "Please:\n"
            "1. Research the company online if needed to gather additional context, "
            "competitive positioning, financial metrics, and industry trends.\n"
            "2. Complete and improve the thesis using the structure shown in the examples.\n"
            "3. Ensure all sections are filled out with specific, thoughtful content.\n"
            "4. Include concrete reasoning grounded in company fundamentals.\n"
            "5. Return ONLY the completed thesis markdown, with no additional commentary.\n"
            "6. Do not include code fences or markdown syntax markers; return pure markdown.\n"
            "7. Maintain the same structure as the examples (Position, What [Company] is, "
            "Core investment thesis, company-level edge, etc.)\n"
            "8. Make it 2-3 paragraphs per section where appropriate to provide depth.\n"
            "9. The output should be ready to use immediately as an investment thesis document."
        )

        return create_response_text(
            self.client,
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            error_type=ThesisGeneratorError,
            web_search=True,
        )


def main():
    load_environment()
    parser = argparse.ArgumentParser(
        description=(
            "Generate and refine investment theses using OpenAI. "
            "Accepts draft thesis files and produces completed, well-formatted theses."
        )
    )
    parser.add_argument(
        "thesis_file",
        help="Path to the draft thesis markdown file to improve",
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help="Override the OpenAI model (default: OPENAI_MODEL or gpt-4.1-mini)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full tracebacks for unexpected errors.",
    )

    args = parser.parse_args()
    thesis_path = Path(args.thesis_file)

    if not thesis_path.exists():
        print(f"Error: Thesis file not found: {thesis_path}")
        sys.exit(1)

    draft_text = thesis_path.read_text(encoding="utf-8")

    if not draft_text.strip():
        print("Error: Thesis file is empty.")
        sys.exit(1)

    print(f"Reading draft thesis from: {thesis_path}")
    print("Generating improved thesis with OpenAI...")

    try:
        generator = ThesisGenerator(model=args.openai_model)
        improved_thesis = generator.generate(draft_text)
    except ThesisGeneratorError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        report_unexpected_error(exc, verbose=args.verbose, prefix="")
        sys.exit(1)

    # Keep the original draft so a poor generation never destroys the user's notes.
    backup_path = thesis_path.with_name(thesis_path.name + ".bak")
    shutil.copy2(thesis_path, backup_path)

    write_text_atomic(thesis_path, improved_thesis)

    print(f"Thesis saved to: {thesis_path} (original draft backed up to {backup_path.name})")
    print("\nGenerated thesis preview (first 500 chars):\n")
    print(improved_thesis[:500] + "...\n")


if __name__ == "__main__":
    main()
