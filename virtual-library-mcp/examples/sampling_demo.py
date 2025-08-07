#!/usr/bin/env python3
"""
MCP Sampling Demonstration Script

This standalone script demonstrates how MCP sampling works by simulating
the interaction between a server and client. It shows the complete flow
of a sampling request and helps developers understand the protocol.

Run this script to see:
1. How sampling requests are constructed
2. What the client sees and approves
3. How responses are processed
4. Error handling scenarios

Usage:
    python examples/sampling_demo.py
"""

import asyncio
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ModelHint,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)


class SamplingDemo:
    """Demonstrates MCP sampling with educational output."""

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self.request_count = 0

    def print_section(self, title: str):
        """Print a formatted section header."""
        print(f"\n{'=' * 60}")
        print(f" {title}")
        print(f"{'=' * 60}\n")

    def print_step(self, step: int, description: str):
        """Print a numbered step."""
        print(f"\n[Step {step}] {description}")
        print("-" * 40)

    async def simulate_sampling_request(
        self,
        prompt: str,
        system_prompt: str | None = None,
        simulate_success: bool = True,
        simulate_user_rejection: bool = False,
    ) -> str | None:
        """
        Simulate a complete sampling request cycle.

        In a real implementation, this would use context.session.create_message()
        """
        self.request_count += 1

        self.print_section(f"Sampling Request #{self.request_count}")

        # Step 1: Build the request
        self.print_step(1, "Building Sampling Request")

        request = CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            modelPreferences=ModelPreferences(
                hints=[
                    ModelHint(name="claude-3-sonnet"),
                    ModelHint(name="claude"),
                ],
                intelligence_priority=0.8,
                speed_priority=0.5,
                cost_priority=0.3,
            ),
            maxTokens=500,
            temperature=0.7,
        )

        if system_prompt:
            request.systemPrompt = system_prompt

        # Show the request structure
        print("Request structure:")
        print(f"  Messages: {len(request.messages)} message(s)")
        print(f"  First message role: {request.messages[0].role}")
        print(f"  Prompt preview: {prompt[:100]}...")
        print(f"  System prompt: {'Yes' if system_prompt else 'No'}")
        print(f"  Max tokens: {request.maxTokens}")
        print(f"  Temperature: {request.temperature}")
        print("\nModel preferences:")
        print(f"  Intelligence priority: {request.modelPreferences.intelligence_priority}")
        print(f"  Speed priority: {request.modelPreferences.speed_priority}")
        print(f"  Cost priority: {request.modelPreferences.cost_priority}")
        print(f"  Model hints: {[hint.name for hint in request.modelPreferences.hints]}")

        # Step 2: Simulate client processing
        self.print_step(2, "Client Processing")

        if simulate_user_rejection:
            print("❌ USER ACTION: Rejected sampling request")
            print("   Reason: User chose not to send data to LLM")
            return None

        print("✅ USER ACTION: Approved sampling request")
        print("   The client would now send this to the configured LLM...")

        # Step 3: Simulate LLM response
        self.print_step(3, "LLM Response")

        if not simulate_success:
            print("❌ ERROR: LLM request failed")
            print("   Error: Connection timeout after 30 seconds")
            return None

        # Simulate a response based on the prompt
        if "summary" in prompt.lower():
            simulated_response = """This compelling work explores the intersection of technology and human creativity. Through carefully crafted examples and practical wisdom, it guides readers on a journey of discovery. The author's unique perspective challenges conventional thinking while providing actionable insights that readers can immediately apply."""
        elif "themes" in prompt.lower():
            simulated_response = """1. **Innovation and Progress**: The constant push toward new solutions and ideas.
2. **Human Connection**: How technology impacts our relationships and communication.
3. **Ethical Responsibility**: The moral obligations that come with technological power.
4. **Learning and Growth**: The importance of continuous adaptation and skill development."""
        elif "discussion" in prompt.lower():
            simulated_response = """1. How did this book challenge your existing beliefs about the topic?
2. Which concept resonated most strongly with your personal experience?
3. What practical applications can you see for these ideas in your daily life?
4. How might the world be different if everyone applied these principles?
5. What questions does this book leave unanswered for you?"""
        else:
            simulated_response = (
                "This is a simulated LLM response demonstrating how sampling works in MCP."
            )

        result = CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=simulated_response),
            model="claude-3-sonnet-20240307",
            stop_reason="end_turn",
        )

        print(f"Model used: {result.model}")
        print(f"Stop reason: {result.stop_reason}")
        print(f"Response length: {len(result.content.text)} characters")
        print("\nGenerated content:")
        print("-" * 40)
        print(result.content.text)
        print("-" * 40)

        return result.content.text

    async def run_demo(self):
        """Run the complete sampling demonstration."""
        self.print_section("MCP Sampling Demonstration")

        print("This script demonstrates how MCP sampling works by simulating")
        print("the interaction between a server and client.")
        print("\nIn a real implementation:")
        print("- The server would use context.session.create_message()")
        print("- The client would show a consent UI to the user")
        print("- The approved request would be sent to an actual LLM")

        # Demo 1: Successful book summary
        await self.simulate_sampling_request(
            prompt="""Generate a compelling summary for this book:
            Title: The Innovator's Dilemma
            Author: Clayton Christensen
            Genre: Business
            Year: 1997""",
            system_prompt="You are a knowledgeable librarian creating engaging book summaries.",
            simulate_success=True,
        )

        # Demo 2: User rejection
        await self.simulate_sampling_request(
            prompt="Generate discussion questions for The Great Gatsby",
            simulate_user_rejection=True,
        )

        # Demo 3: API failure
        await self.simulate_sampling_request(
            prompt="Analyze the themes in 1984 by George Orwell", simulate_success=False
        )

        # Demo 4: Different insight type
        await self.simulate_sampling_request(
            prompt="""Recommend books similar to:
            Title: Sapiens
            Author: Yuval Noah Harari
            Genre: Non-fiction/History""",
            system_prompt="You are a library recommendation expert.",
            simulate_success=True,
        )

        self.print_section("Demo Complete")
        print(f"Total sampling requests: {self.request_count}")
        print("\nKey takeaways:")
        print("1. Always check if the client supports sampling")
        print("2. Users must approve each sampling request")
        print("3. Provide meaningful fallbacks for failures")
        print("4. Use appropriate model preferences for your use case")
        print("5. Include relevant context in your prompts")

        print("\n📚 Next steps:")
        print("- Review the sampling.py module for implementation details")
        print("- Try the book_insights tool with a real MCP client")
        print("- Read the SAMPLING_TUTORIAL.md for more information")


async def main():
    """Run the demonstration."""
    # Check for demo mode flag
    demo_mode = os.environ.get("SAMPLING_DEMO_MODE", "true").lower() == "true"

    if not demo_mode:
        print("Note: SAMPLING_DEMO_MODE is disabled. Set to 'true' to see full output.")

    demo = SamplingDemo(demo_mode=demo_mode)
    await demo.run_demo()


if __name__ == "__main__":
    print("🚀 Starting MCP Sampling Demo...")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Python: {sys.version.split()[0]}")

    asyncio.run(main())
