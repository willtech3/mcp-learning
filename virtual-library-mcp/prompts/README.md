# MCP Prompts - Complete Guide

Prompts are reusable templates that structure interactions between users and LLMs, providing consistent, context-aware AI assistance through parameterized generation.

## Core Concepts

Prompts bridge the gap between raw data and meaningful AI responses. Unlike Resources (data retrieval) or Tools (state modification), Prompts focus on **intelligent content generation**. They transform structured inputs into carefully crafted LLM instructions that produce high-quality, consistent outputs.

The MCP protocol ensures prompts are:
- **Parameterized**: Dynamic generation based on arguments
- **Contextual**: Integrate server-side data for relevance
- **Reusable**: Same prompt serves multiple use cases
- **Discoverable**: Clients list available prompts via `prompts/list`
- **Predictable**: Consistent structure yields reliable outputs

Prompts flow through JSON-RPC 2.0: clients send `prompts/get` requests with prompt name and arguments, servers generate customized prompt text using live data, and return formatted content ready for LLM consumption.

## Implementation Patterns

### Parameter-Driven Generation

Prompts adapt based on inputs:
```python
# From book_recommendations.py - Multiple parameters shape output
async def recommend_books(
    genre: str | None = None,
    mood: str | None = None,
    patron_id: int | None = None,
    limit: int = 5,
    _session=None
) -> str:
    # Build context from parameters
    criteria = []
    if genre:
        criteria.append(f"Genre preference: {genre}")
    if mood:
        criteria.append(f"Current mood: {mood}")
    
    # Fetch relevant data
    if patron_id:
        patron = get_patron(patron_id)
        history = get_reading_history(patron_id)
    
    # Generate dynamic prompt
    return f"""You are a knowledgeable librarian...
    Based on: {', '.join(criteria)}
    Recommend {limit} books..."""
```

### Complex Multi-Section Prompts

Structure guides LLM responses:
```python
# From reading_plan.py - Comprehensive learning plan
async def generate_reading_plan(
    goal: str,
    duration: Literal["week", "month", "quarter", "year"],
    experience_level: Literal["beginner", "intermediate", "advanced"],
    time_commitment: Literal["light", "moderate", "intensive"]
) -> str:
    # Map parameters to concrete values
    duration_books = {"week": 1, "month": 3, "quarter": 8, "year": 24}
    pages_per_week = {"light": 100, "moderate": 250, "intensive": 500}
    
    # Fetch relevant books
    books = search_books_by_goal(goal)
    
    return f"""Create a structured reading plan:
    
    1. **Learning Path Overview**
       - Progress from {experience_level} to next level
       - {duration_books[duration]} books over {duration}
       
    2. **Book Recommendations**
       - Order from foundational to advanced
       - Include why each book matters
       
    3. **Reading Schedule**  
       - {pages_per_week[time_commitment]} pages/week capacity
       - Include review time
       
    4. **Success Metrics**
       - Define completion criteria
       - Suggest knowledge tests"""
```

### Multi-Style Output Generation

Same data, different perspectives:
```python
# From review_generator.py - Style variations
async def generate_book_review(
    isbn: str,
    review_type: Literal["summary", "critical", "recommendation"],
    target_audience: str | None = None,
    include_quotes: bool = False
) -> str:
    # Fetch book data
    book = get_book_by_isbn(isbn)
    metrics = get_circulation_metrics(isbn)
    
    # Style-specific instructions
    review_styles = {
        "summary": "concise overview without spoilers",
        "critical": "balanced analysis of strengths and weaknesses",
        "recommendation": "enthusiastic guide for potential readers"
    }
    
    # Audience adaptation
    audience_context = f"Target: {target_audience}" if target_audience else "General audience"
    
    return f"""Write a {review_type} review:
    Style: {review_styles[review_type]}
    {audience_context}
    {"Include memorable quotes" if include_quotes else ""}
    
    Book: {book.title} by {book.author}
    Popularity: {metrics.checkout_count} checkouts"""
```

## Technical Deep Dive

### Prompt Function Signatures

FastMCP automatically registers prompt functions:
```python
# Decorator-less registration
async def prompt_name(
    required_param: str,
    optional_param: str | None = None,
    typed_param: Literal["option1", "option2"] = "option1",
    _session=None  # Testing injection point
) -> str:
    """Docstring becomes prompt description."""
    # Return prompt text
    return "Generated prompt content..."

# Registration in server.py
mcp.prompt()(prompt_name)
```

Parameters become part of the prompt's JSON Schema, enabling client-side validation and UI generation.

### Database Integration Patterns

Prompts often need fresh data:
```python
# Session management for data access
async def data_driven_prompt(book_id: str, _session=None):
    session = _session or next(get_session())
    should_close = _session is None
    
    try:
        # Fetch current data
        book_repo = BookRepository(session)
        book = book_repo.get_by_id(book_id)
        
        # Get related data
        similar_books = book_repo.get_similar(book.genre, limit=5)
        checkout_stats = get_popularity_metrics(book_id)
        
        # Build prompt with live data
        return f"""Book: {book.title}
        Current availability: {book.available_copies} copies
        Popularity: {checkout_stats.rank} in {book.genre}
        Similar books: {format_book_list(similar_books)}"""
        
    finally:
        if should_close:
            session.close()
```

### Context Building Strategies

Layer context for richer prompts:
```python
# Base context
base_context = f"You are a librarian at {LIBRARY_NAME}."

# User context
if user_id:
    user = get_user(user_id)
    user_context = f"Helping {user.name}, member since {user.join_date}"
else:
    user_context = "Helping a library visitor"

# Temporal context  
temporal_context = f"Today is {datetime.now().strftime('%A, %B %d')}"
if is_holiday():
    temporal_context += " (holiday hours in effect)"

# Domain context
if genre == "children":
    domain_context = "Focus on age-appropriate content with educational value"
else:
    domain_context = "Consider literary merit and reader engagement"

# Combine all contexts
full_prompt = f"""{base_context}
{user_context}
{temporal_context}
{domain_context}

Task: {specific_request}"""
```

### Output Formatting Strategies

Guide structure without overconstraining:
```python
# Structured sections
return f"""Please provide your response in these sections:

## Summary (2-3 sentences)
{summary_guidance}

## Main Content
{content_requirements}

## Additional Resources
- Related books
- External references
- Next steps

Format using markdown for clarity."""

# Flexible formatting with examples
return f"""Recommend books in a conversational tone.

Example format:
"For {mood} mood, I'd suggest '{title}' because..."

Include:
- Why each book matches the mood
- Reading order if books are related
- Content warnings if applicable"""
```

### Token Optimization

Manage prompt length efficiently:
```python
# Truncate long lists
MAX_BOOKS_IN_PROMPT = 20
relevant_books = search_books(query)[:MAX_BOOKS_IN_PROMPT]

# Summarize verbose data
book_summary = f"{book.title} ({book.year}) - {book.genre}"
# Instead of including full description

# Use references instead of repetition
book_ids = [b.id for b in books]
return f"""Recommend from books: {book_ids}
(Full details available via library://books/{id})"""

# Conditional inclusion
if include_detailed_history:
    prompt += format_reading_history(patron_id)
else:
    prompt += f"Patron has read {history_count} books"
```

## Best Practices

### Prompt Clarity and Structure

Write prompts that guide without overconstraining:

```python
# Good: Clear role and task
"You are a library book recommendation expert. Based on the patron's reading history in mystery novels, suggest 5 similar books they haven't read yet."

# Bad: Vague or overspecified
"You are an AI. List some books."
# or
"You must respond with exactly 5 books, each with a 47-word description..."
```

### Consistency Across Prompts

Maintain voice and structure:
```python
# Shared prompt components
LIBRARIAN_PERSONA = "You are a knowledgeable, friendly librarian who loves connecting readers with their next great book."

RESPONSE_GUIDELINES = """
- Use encouraging, accessible language
- Avoid literary jargon unless appropriate
- Include why each recommendation fits
- Mention availability in our library
"""

# Reuse in multiple prompts
async def genre_recommendations():
    return f"""{LIBRARIAN_PERSONA}
    
    Task: Recommend {genre} books
    {RESPONSE_GUIDELINES}"""
```

### Testing Prompt Outputs

Validate prompt effectiveness:
```python
# Test with edge cases
test_cases = [
    {"genre": "nonexistent", "expected": "graceful handling"},
    {"mood": "angry", "expected": "appropriate suggestions"},
    {"limit": 0, "expected": "error or default"}
]

# Measure consistency
async def test_prompt_consistency():
    results = []
    for _ in range(5):
        output = await generate_prompt(same_params)
        results.append(output)
    
    # Check structural consistency
    assert all("## Summary" in r for r in results)
```

### Dynamic Adaptation

Adjust based on context:
```python
# Time-based adaptation
current_season = get_current_season()
if current_season == "summer":
    prompt += "\nConsider beach reads and adventure stories"
elif current_season == "winter":
    prompt += "\nConsider cozy mysteries and epic fantasies"

# User expertise adaptation
if experience_level == "advanced":
    prompt += "\nInclude complex narratives and experimental works"
else:
    prompt += "\nFocus on accessible, well-paced stories"

# Availability adaptation
if all_digital:
    prompt += "\nOnly recommend books available in digital format"
```

## Advanced Patterns

### Chained Prompts

Build complex interactions:
```python
# First prompt: Gather preferences
preferences_prompt = await gather_reading_preferences(patron_id)
# LLM responds with structured preferences

# Second prompt: Generate recommendations
recommendations = await generate_recommendations(
    preferences=llm_response,
    constraints=library_constraints
)

# Third prompt: Create reading schedule
schedule = await create_reading_schedule(
    books=recommendations,
    timeline=user_timeline
)
```

### Meta-Prompts

Prompts that generate prompts:
```python
async def create_custom_recommendation_prompt(
    description: str,
    constraints: list[str]
) -> str:
    return f"""Create a book recommendation prompt that:
    - Achieves: {description}
    - Respects constraints: {', '.join(constraints)}
    - Uses available library data
    - Produces consistent results
    
    Output the prompt template with {placeholder} markers."""
```

### Feedback Integration

Improve prompts based on usage:
```python
# Track prompt effectiveness
async def recommendation_with_feedback(params):
    prompt = generate_base_prompt(params)
    
    # Add historical performance data
    past_success = get_prompt_metrics("recommendations")
    if past_success.acceptance_rate < 0.5:
        prompt += "\nNote: Users prefer diverse genre suggestions"
    
    return prompt
```

## Examples in This Repository

| Pattern | File | Description |
|---------|------|-------------|
| Multi-parameter prompts | `book_recommendations.py` | Genre, mood, patron-based |
| Complex structured output | `reading_plan.py` | Multi-section learning plans |
| Style variations | `review_generator.py` | Different review types |
| Data integration | All files | Live database queries |
| Token optimization | All files | Efficient data inclusion |

## Prompt Engineering Tips

### Effective Instructions

```python
# Be specific about format
"List each book as: Title by Author (Year) - Brief reason for recommendation"

# Provide examples
"Example: 'The Hobbit by J.R.R. Tolkien (1937) - Perfect starting point for fantasy lovers'"

# Set constraints clearly
"Maximum 2 books per genre, prefer available copies"
```

### Common Pitfalls

```python
# Avoid: Contradictory instructions
"Be creative but follow this exact format..."

# Avoid: Assumed knowledge  
"Recommend books like the usual ones"  # What's usual?

# Avoid: Open-ended without guidance
"Tell me about books"  # Too vague
```

### Performance Optimization

```python
# Cache expensive computations
@lru_cache(maxsize=100)
def get_genre_statistics(genre: str):
    # Expensive database aggregation
    return calculate_genre_metrics(genre)

# Batch data fetching
book_ids = extract_book_ids(params)
books = batch_fetch_books(book_ids)  # One query instead of N

# Precompute common elements
STANDARD_FOOTER = compute_library_hours_text()
```

## Related Documentation

- [Resources README](../resources/README.md) - Data retrieval patterns
- [Tools README](../tools/README.md) - State modification patterns
- [MCP Specification](https://modelcontextprotocol.io/docs/specification)
- [Prompt Engineering Guide](https://platform.openai.com/docs/guides/prompt-engineering)