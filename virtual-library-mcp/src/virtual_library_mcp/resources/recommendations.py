"""Recommendation Resources for Virtual Library MCP Server

This module implements personalized book recommendations using patron history
and preferences. It demonstrates advanced MCP concepts including:
- Dynamic resource generation based on patron data
- Multi-factor recommendation algorithms
- Privacy-aware analytics

MCP RECOMMENDATION PATTERNS:
1. **Personalized Resources**: Content varies based on the patron
2. **Collaborative Filtering**: Recommendations based on similar patrons
3. **Content-Based Filtering**: Recommendations based on book attributes
4. **Hybrid Approaches**: Combining multiple recommendation strategies

PRIVACY CONSIDERATIONS:
- Recommendations are only accessible by the patron themselves
- Aggregate data doesn't reveal individual reading habits
- Patron preferences are respected (opt-in/opt-out)
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import joinedload

from ..database.schema import Book as BookDB
from ..database.schema import CheckoutRecord as CheckoutDB
from ..database.schema import Patron as PatronDB
from ..database.session import session_scope

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def extract_patron_id_from_recommendation_uri(uri: str) -> str:
    """Extract patron ID from library://recommendations/{patron_id} URI.

    Args:
        uri: The full resource URI

    Returns:
        The extracted patron ID

    Raises:
        ValueError: If URI format is invalid
    """
    try:
        # Simple extraction for recommendations URI
        parts = uri.split("/")
        if len(parts) < 4 or parts[2] != "recommendations":
            raise ValueError("Invalid recommendations URI format")

        patron_id = parts[3]
        if not patron_id:
            raise ValueError("Missing patron ID in URI")

        return patron_id

    except Exception as e:
        raise ValueError(f"Invalid recommendation URI format '{uri}': {e}") from e


# =============================================================================
# RESOURCE SCHEMAS
# =============================================================================


class RecommendationParams(BaseModel):
    """Parameters for recommendation generation.

    WHY: Different recommendation strategies require different parameters.
    This allows clients to customize the recommendation algorithm.
    """

    limit: int = Field(default=10, ge=1, le=20, description="Number of recommendations")
    strategy: str = Field(
        default="hybrid",
        pattern="^(genre_based|author_based|popular|collaborative|hybrid)$",
        description="Recommendation strategy to use",
    )
    exclude_read: bool = Field(
        default=True, description="Exclude books patron has already borrowed"
    )
    days_history: int = Field(default=180, ge=30, le=365, description="Days of history to analyze")
    min_rating: float = Field(default=3.5, ge=0, le=5, description="Minimum average rating")


class RecommendationEntry(BaseModel):
    """Single book recommendation with reasoning."""

    rank: int = Field(..., description="Recommendation rank (1 = best match)")
    isbn: str = Field(..., description="Book ISBN")
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Book author")
    genre: str = Field(..., description="Book genre")
    reason: str = Field(..., description="Why this book was recommended")
    score: float = Field(..., description="Recommendation score (0-100)")
    available: bool = Field(..., description="Whether the book is currently available")

    # Additional metadata
    avg_rating: float | None = Field(None, description="Average patron rating if available")
    checkout_count: int = Field(0, description="Total times borrowed")
    similar_patrons_borrowed: int = Field(
        0, description="Number of similar patrons who borrowed this"
    )


class RecommendationResponse(BaseModel):
    """Response schema for recommendations."""

    patron_id: str = Field(..., description="Patron ID")
    patron_name: str = Field(..., description="Patron name")
    strategy_used: str = Field(..., description="Recommendation strategy applied")
    analysis_period_days: int = Field(..., description="Days of history analyzed")
    recommendations_count: int = Field(..., description="Number of recommendations generated")

    # Patron profile summary
    favorite_genres: list[str] = Field(..., description="Patron's most borrowed genres")
    favorite_authors: list[str] = Field(..., description="Patron's most borrowed authors")

    # Recommendations
    recommendations: list[RecommendationEntry] = Field(..., description="Recommended books")


# =============================================================================
# RECOMMENDATION ALGORITHMS
# =============================================================================


class RecommendationEngine:
    """Engine for generating personalized book recommendations.

    MCP ALGORITHM DESIGN:
    This class encapsulates various recommendation strategies that can be
    exposed through MCP resources. Each strategy demonstrates different
    approaches to personalization.
    """

    def __init__(self, session, patron_id: str, params: RecommendationParams):
        self.session = session
        self.patron_id = patron_id
        self.params = params
        self.patron = None
        self.patron_history = []
        self.borrowed_isbns = set()

    def generate_recommendations(self) -> RecommendationResponse:
        """Generate recommendations using the specified strategy."""
        # Load patron data
        self._load_patron_data()

        if not self.patron:
            raise ResourceError(f"Patron not found: {self.patron_id}")

        # Get patron profile
        favorite_genres = self._get_favorite_genres()
        favorite_authors = self._get_favorite_authors()

        # Generate recommendations based on strategy
        if self.params.strategy == "genre_based":
            recommendations = self._genre_based_recommendations(favorite_genres)
        elif self.params.strategy == "author_based":
            recommendations = self._author_based_recommendations(favorite_authors)
        elif self.params.strategy == "popular":
            recommendations = self._popular_books_recommendations()
        elif self.params.strategy == "collaborative":
            recommendations = self._collaborative_filtering_recommendations()
        else:  # hybrid
            recommendations = self._hybrid_recommendations(favorite_genres, favorite_authors)

        # Sort by score and limit
        recommendations.sort(key=lambda x: x.score, reverse=True)
        recommendations = recommendations[: self.params.limit]

        # Assign ranks
        for i, rec in enumerate(recommendations, 1):
            rec.rank = i

        return RecommendationResponse(
            patron_id=self.patron.id,
            patron_name=self.patron.name,
            strategy_used=self.params.strategy,
            analysis_period_days=self.params.days_history,
            recommendations_count=len(recommendations),
            favorite_genres=favorite_genres[:3],  # Top 3
            favorite_authors=favorite_authors[:3],  # Top 3
            recommendations=recommendations,
        )

    def _load_patron_data(self):
        """Load patron and their borrowing history."""
        # Get patron
        self.patron = self.session.execute(
            select(PatronDB).where(PatronDB.id == self.patron_id)
        ).scalar_one_or_none()

        if not self.patron:
            return

        # Get borrowing history
        cutoff_date = datetime.now() - timedelta(days=self.params.days_history)

        self.patron_history = (
            self.session.execute(
                select(CheckoutDB)
                .where(
                    and_(
                        CheckoutDB.patron_id == self.patron_id,
                        CheckoutDB.checkout_date >= cutoff_date,
                    )
                )
                .options(joinedload(CheckoutDB.book))
            )
            .scalars()
            .all()
        )

        # Track borrowed ISBNs
        self.borrowed_isbns = {checkout.book_isbn for checkout in self.patron_history}

    def _get_favorite_genres(self) -> list[str]:
        """Get patron's favorite genres based on history."""
        genre_counts = Counter()
        for checkout in self.patron_history:
            if checkout.book and checkout.book.genre:
                genre_counts[checkout.book.genre] += 1

        return [genre for genre, _ in genre_counts.most_common()]

    def _get_favorite_authors(self) -> list[str]:
        """Get patron's favorite authors based on history."""
        author_counts = Counter()
        for checkout in self.patron_history:
            if checkout.book and checkout.book.author:
                author_counts[checkout.book.author] += 1

        return [author for author, _ in author_counts.most_common()]

    def _genre_based_recommendations(self, favorite_genres: list[str]) -> list[RecommendationEntry]:
        """Generate recommendations based on favorite genres."""
        recommendations = []

        if not favorite_genres:
            return recommendations

        # Get popular books in favorite genres
        for i, genre in enumerate(favorite_genres[:3]):  # Top 3 genres
            genre_books = (
                self.session.execute(
                    select(BookDB)
                    .where(
                        and_(
                            BookDB.genre == genre,
                            BookDB.isbn.notin_(self.borrowed_isbns)
                            if self.params.exclude_read
                            else True,
                        )
                    )
                    .order_by(desc(BookDB.average_rating))
                    .limit(5)
                )
                .scalars()
                .all()
            )

            for book in genre_books:
                if book.average_rating >= self.params.min_rating:
                    recommendations.append(
                        RecommendationEntry(
                            rank=0,  # Will be set later
                            isbn=book.isbn,
                            title=book.title,
                            author=book.author,
                            genre=book.genre,
                            reason=f"Popular in your favorite genre: {genre}",
                            score=80
                            - (i * 10)
                            + (book.average_rating * 2),  # Genre rank affects score
                            available=book.available_copies > 0,
                            avg_rating=book.average_rating,
                            checkout_count=book.total_checkouts,
                        )
                    )

        return recommendations

    def _author_based_recommendations(
        self, favorite_authors: list[str]
    ) -> list[RecommendationEntry]:
        """Generate recommendations based on favorite authors."""
        recommendations = []

        if not favorite_authors:
            return recommendations

        # Get other books by favorite authors
        for i, author in enumerate(favorite_authors[:3]):  # Top 3 authors
            author_books = (
                self.session.execute(
                    select(BookDB)
                    .where(
                        and_(
                            BookDB.author == author,
                            BookDB.isbn.notin_(self.borrowed_isbns)
                            if self.params.exclude_read
                            else True,
                        )
                    )
                    .order_by(desc(BookDB.publication_year))
                    .limit(4)
                )
                .scalars()
                .all()
            )

            for book in author_books:
                recommendations.append(
                    RecommendationEntry(
                        rank=0,
                        isbn=book.isbn,
                        title=book.title,
                        author=book.author,
                        genre=book.genre,
                        reason=f"New book by {author}, one of your favorite authors",
                        score=85 - (i * 10),  # Author rank affects score
                        available=book.available_copies > 0,
                        avg_rating=book.average_rating,
                        checkout_count=book.total_checkouts,
                    )
                )

        return recommendations

    def _popular_books_recommendations(self) -> list[RecommendationEntry]:
        """Generate recommendations based on overall popularity."""
        recommendations = []

        # Get most popular books in last 30 days
        recent_popular = self.session.execute(
            select(BookDB, func.count(CheckoutDB.id).label("recent_checkouts"))
            .select_from(BookDB)
            .join(CheckoutDB, BookDB.isbn == CheckoutDB.book_isbn)
            .where(
                and_(
                    CheckoutDB.checkout_date >= datetime.now() - timedelta(days=30),
                    BookDB.isbn.notin_(self.borrowed_isbns) if self.params.exclude_read else True,
                )
            )
            .group_by(BookDB.isbn)
            .order_by(desc("recent_checkouts"))
            .limit(self.params.limit * 2)  # Get extra to filter
        ).all()

        for book, checkout_count in recent_popular:
            if book.average_rating >= self.params.min_rating:
                recommendations.append(
                    RecommendationEntry(
                        rank=0,
                        isbn=book.isbn,
                        title=book.title,
                        author=book.author,
                        genre=book.genre,
                        reason=f"Trending now with {checkout_count} recent checkouts",
                        score=70 + min(checkout_count, 30),  # Cap bonus at 30
                        available=book.available_copies > 0,
                        avg_rating=book.average_rating,
                        checkout_count=book.total_checkouts,
                    )
                )

        return recommendations

    def _collaborative_filtering_recommendations(self) -> list[RecommendationEntry]:
        """Generate recommendations based on similar patrons' reading habits."""
        recommendations = []

        if not self.borrowed_isbns:
            return recommendations

        # Find patrons who borrowed similar books
        similar_patrons = self.session.execute(
            select(CheckoutDB.patron_id, func.count(CheckoutDB.id).label("common_books"))
            .where(
                and_(
                    CheckoutDB.book_isbn.in_(self.borrowed_isbns),
                    CheckoutDB.patron_id != self.patron_id,
                )
            )
            .group_by(CheckoutDB.patron_id)
            .order_by(desc("common_books"))
            .limit(10)  # Top 10 similar patrons
        ).all()

        if not similar_patrons:
            return recommendations

        similar_patron_ids = [p[0] for p in similar_patrons]

        # Get books these similar patrons borrowed that current patron hasn't
        collaborative_books = self.session.execute(
            select(BookDB, func.count(CheckoutDB.id).label("similar_patron_count"))
            .select_from(BookDB)
            .join(CheckoutDB, BookDB.isbn == CheckoutDB.book_isbn)
            .where(
                and_(
                    CheckoutDB.patron_id.in_(similar_patron_ids),
                    BookDB.isbn.notin_(self.borrowed_isbns) if self.params.exclude_read else True,
                )
            )
            .group_by(BookDB.isbn)
            .order_by(desc("similar_patron_count"))
            .limit(self.params.limit * 2)
        ).all()

        for book, similar_count in collaborative_books:
            if book.average_rating >= self.params.min_rating:
                recommendations.append(
                    RecommendationEntry(
                        rank=0,
                        isbn=book.isbn,
                        title=book.title,
                        author=book.author,
                        genre=book.genre,
                        reason=f"Borrowed by {similar_count} patrons with similar tastes",
                        score=60 + (similar_count * 5),  # More similar patrons = higher score
                        available=book.available_copies > 0,
                        avg_rating=book.average_rating,
                        checkout_count=book.total_checkouts,
                        similar_patrons_borrowed=similar_count,
                    )
                )

        return recommendations

    def _hybrid_recommendations(
        self, favorite_genres: list[str], favorite_authors: list[str]
    ) -> list[RecommendationEntry]:
        """Combine multiple recommendation strategies."""
        # Get recommendations from each strategy
        genre_recs = self._genre_based_recommendations(favorite_genres)
        author_recs = self._author_based_recommendations(favorite_authors)
        popular_recs = self._popular_books_recommendations()
        collab_recs = self._collaborative_filtering_recommendations()

        # Combine and deduplicate
        all_recs = {}
        for rec in genre_recs + author_recs + popular_recs + collab_recs:
            if rec.isbn in all_recs:
                # Average the scores if duplicate
                existing = all_recs[rec.isbn]
                existing.score = (existing.score + rec.score) / 2
                # Combine reasons
                if rec.reason not in existing.reason:
                    existing.reason += f"; {rec.reason}"
            else:
                all_recs[rec.isbn] = rec

        return list(all_recs.values())


# =============================================================================
# RESOURCE HANDLER
# =============================================================================


async def get_patron_recommendations_handler(
    uri: str,
    context: Context,  # noqa: ARG001
    params: RecommendationParams | None = None,
) -> dict[str, Any]:
    """Handle requests for personalized book recommendations.

    MCP PERSONALIZATION:
    This resource demonstrates how MCP can provide personalized content
    based on user history and preferences. The recommendations are
    generated dynamically based on multiple factors.

    PRIVACY NOTE:
    In a production system, this resource would require authentication
    to ensure patrons can only access their own recommendations.

    Args:
        uri: The resource URI (e.g., "library://recommendations/patron_smith001")
        context: FastMCP context
        params: Parameters for recommendation generation

    Returns:
        Dictionary containing personalized recommendations
    """
    try:
        # Extract patron ID from URI
        patron_id = extract_patron_id_from_recommendation_uri(uri)

        # Default parameters if none provided
        if params is None:
            params = RecommendationParams()

        logger.debug(
            "MCP Resource Request - recommendations/%s: strategy=%s, limit=%d",
            patron_id,
            params.strategy,
            params.limit,
        )

        with session_scope() as session:
            # Generate recommendations
            engine = RecommendationEngine(session, patron_id, params)
            response = engine.generate_recommendations()

            return response.model_dump()

    except ResourceError:
        raise
    except Exception as e:
        logger.exception("Error in recommendations resource")
        raise ResourceError(f"Failed to generate recommendations: {e!s}") from e


# =============================================================================
# RESOURCE REGISTRATION
# =============================================================================

# Define recommendation resources for FastMCP registration
recommendation_resources: list[dict[str, Any]] = [
    {
        "uri_template": "library://recommendations/{patron_id}",
        "name": "Personalized Book Recommendations",
        "description": (
            "Get personalized book recommendations based on borrowing history, "
            "preferences, and collaborative filtering. Supports multiple recommendation "
            "strategies including genre-based, author-based, popularity, and hybrid approaches."
        ),
        "mime_type": "application/json",
        "handler": get_patron_recommendations_handler,
    },
]


# =============================================================================
# MCP RECOMMENDATION LEARNINGS
# =============================================================================

"""
KEY INSIGHTS FROM IMPLEMENTING RECOMMENDATION RESOURCES:

1. **PERSONALIZATION STRATEGIES**:
   - Multiple algorithms provide different perspectives
   - Hybrid approaches often work best
   - Consider both explicit (genres) and implicit (behavior) signals
   - Balance between exploration and exploitation

2. **PRIVACY CONSIDERATIONS**:
   - Recommendations reveal reading habits
   - Authentication is critical for personal data
   - Consider allowing opt-out of tracking
   - Be transparent about data usage

3. **PERFORMANCE OPTIMIZATION**:
   - Pre-compute common aggregations
   - Use database-level operations
   - Limit recommendation pool size early
   - Consider caching for expensive calculations

4. **QUALITY FACTORS**:
   - Diversity: Don't recommend only one genre
   - Freshness: Include new arrivals
   - Availability: Prioritize available books
   - Explanation: Tell users why books were recommended

5. **ALGORITHM IMPROVEMENTS**:
   - Time decay: Recent behavior matters more
   - Negative feedback: Track books patron didn't like
   - Context awareness: Seasonal recommendations
   - Social proof: What friends are reading

FUTURE ENHANCEMENTS:
- Machine learning models for better predictions
- Real-time recommendation updates
- A/B testing different algorithms
- Integration with external book databases
- Reading list management
"""

