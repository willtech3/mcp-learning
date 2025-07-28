# Review PRs

This command reviews pull requests against their corresponding GitHub issues and project principles.

## Usage
`/review_prs <issue_number> <pr_count> [pr_references]`

## Arguments
- `issue_number` (required): The GitHub issue number the PRs are addressing
- `pr_count` (required): Number of PRs addressing the issue
- `pr_references` (optional): Comma-separated PR numbers (e.g., "42,43,44")

## Examples
- `/review_prs 6 3 42,43,44` - Review PRs #42, #43, #44 against issue #6
- `/review_prs 10 2` - Review 2 PRs against issue #10 (will search for open PRs)

## Instructions

1. **Fetch Issue Requirements**:
   - Use `mcp__github__get_issue` to get the issue details from willtech3/mcp-learning
   - Extract acceptance criteria, requirements, and implementation expectations

2. **Identify PRs**:
   - If PR references provided: use those specific PR numbers
   - If not provided: use `mcp__github__list_pull_requests` to find open PRs mentioning the issue

3. **For Each PR**:
   - Use `mcp__github__get_pull_request` to get PR details
   - Use `mcp__github__get_pull_request_files` to see changed files
   - Use `mcp__github__get_pull_request_diff` to analyze implementation details
   - Fetch and checkout the PR branch locally using:
     ```bash
     git fetch origin pull/<pr_number>/head:pr-<pr_number>
     git checkout pr-<pr_number>
     ```

4. **Assess Implementation Completeness**:
   - Map each requirement from the issue to implemented code
   - Check if all acceptance criteria are addressed
   - Identify missing or incomplete implementations
   - Verify edge cases are handled

5. **Verify Project Compliance** (from CLAUDE.md):
   - **Critical Rules**:
     - Ensure no secrets in commits
     - Confirm MCP Protocol Mentor usage for MCP features
   - **Code Standards**:
     - Python 3.12+ features used appropriately
     - FastMCP 2.0 patterns followed
     - Type hints with Pyright compliance
     - Pydantic v2 for data validation
     - SQLAlchemy for database operations
   - **Testing**:
     - Tests follow TDD principles
     - Test behavior, not implementation
     - Use pytest fixtures over mocks
     - Focus on critical paths
   - **MCP Concepts** (if applicable):
     - Resources: Read-only endpoints implemented correctly
     - Tools: Side effects handled properly
     - Prompts: LLM interaction templates well-structured
     - Error handling: Proper JSON-RPC responses

6. **Run Quality Checks**:
   ```bash
   just lint        # Check code style
   just typecheck   # Verify type safety
   just test        # Run test suite
   ```

7. **Generate Objective Assessment**:
   For each PR, provide:
   - **Completeness Score**: X/Y requirements implemented
   - **Compliance Checklist**:
     - [ ] No hardcoded secrets
     - [ ] Type hints complete
     - [ ] Tests included
     - [ ] Follows MCP patterns (if applicable)
   - **Missing Implementation**: List unaddressed requirements
   - **Code Quality Issues**: Specific violations found
   - **Recommendations**: Actionable improvements needed

8. **Summary Comparison**:
   - Rank PRs by completeness and compliance
   - Highlight which PR best addresses the issue
   - Note any unique strengths/approaches in each PR
   - Add any additional feedback that should be addressed before merging.

9. **Select Best Implementation**:
   - Choose the PR with highest combined completeness and compliance scores
   - If tied, prioritize: completeness > test coverage > code quality > unique features
   - Document the selection rationale

10. **Post PR Reviews**:
    - **For Selected PR**: Use `mcp__github__add_issue_comment` to post:
      ```
      🎉 **Selected Implementation for Issue #<issue_number>**
      
      This PR has been selected as the best implementation based on:
      - Completeness: X/Y requirements (X%)
      - Compliance Score: X/10
      - [Additional selection reasons]
      
      **Strengths:**
      - [List key strengths]
      
      **Before Merging:**
      - [List any remaining items to address]
      ```
    
    - **For Non-Selected PRs**: Post feedback explaining why not selected:
      ```
      Thank you for your contribution to Issue #<issue_number>!
      
      After reviewing all PRs, we've selected PR #X for merge. Your PR was not selected due to:
      
      **Missing Requirements:**
      - [List unimplemented requirements]
      
      **Compliance Issues:**
      - [List project compliance violations]
      
      **Comparison:**
      - Your PR: X/Y requirements (X%), Compliance: X/10
      - Selected PR: Y/Y requirements (Y%), Compliance: Y/10
      
      **Your Unique Strengths:**
      - [Acknowledge any good approaches/features]
      
      Please feel free to address these issues if you'd like to continue working on this, or contribute to other open issues!
      ```

## Output Format
```
## PR Review: Issue #<issue_number>

### Issue Requirements Summary
<extracted requirements from issue>

### PR #<number> Assessment
**Completeness**: X/Y requirements (X%)
**Compliance Score**: X/10

**Implemented**:
-  Requirement 1
-  Requirement 2

**Missing**:
-  Requirement 3

**Project Compliance**:
-  Uses justfile commands
-  Missing type hints in module X

**Quality Check Results**:
- Lint: X issues
- Type check: X errors
- Tests: X/Y passing

### Comparative Summary
Best implementation: PR #X (reasoning)

### Selection Decision
**Selected PR**: #X
**Reason**: [Detailed explanation]

### Comments Posted
- ✓ Selection comment posted to PR #X
- ✓ Feedback posted to PR #Y
- ✓ Feedback posted to PR #Z
```

## Context
- GitHub Repository: willtech3/mcp-learning
- Project uses GitHub issues for roadmap tracking
- Virtual Library MCP Server implementation
- Strict adherence to CLAUDE.md principles required