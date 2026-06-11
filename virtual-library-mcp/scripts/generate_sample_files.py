#!/usr/bin/env python3
"""Regenerate the bulk-import sample files in data/samples/.

The samples feed the ``bulk_import_books`` MCP tool demo. Every entry is a
real title by an author intentionally NOT in the curated seed catalog, so a
demo import adds genuinely new books instead of colliding with existing ISBNs.

ISBNs are synthetic-but-valid ISBN-13s derived from title+author, using the
same scheme as database/seed.py.

Usage:
    python scripts/generate_sample_files.py
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.seed import isbn13_for

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"

# Each entry is (title, author, genre, publication_year).
# Small CSV sample: a quick 10-book import demo.
SAMPLE_CSV_BOOKS = [
    ("Lonesome Dove", "Larry McMurtry", "Historical Fiction", 1985),
    ("The Road", "Cormac McCarthy", "Dystopian", 2006),
    ("Blood Meridian", "Cormac McCarthy", "Historical Fiction", 1985),
    ("Gilead", "Marilynne Robinson", "Fiction", 2004),
    ("Stoner", "John Williams", "Fiction", 1965),
    ("Revolutionary Road", "Richard Yates", "Fiction", 1961),
    ("The Age of Innocence", "Edith Wharton", "Fiction", 1920),
    ("My Antonia", "Willa Cather", "Fiction", 1918),
    ("The Call of the Wild", "Jack London", "Adventure", 1903),
    ("A Confederacy of Dunces", "John Kennedy Toole", "Fiction", 1980),
]

# JSON sample: shows optional fields (description, total_copies) in play.
SAMPLE_JSON_BOOKS = [
    ("Cloud Atlas", "David Mitchell", "Science Fiction", 2004),
    ("The Bone Clocks", "David Mitchell", "Fantasy", 2014),
    ("White Teeth", "Zadie Smith", "Fiction", 2000),
    ("The Curious Incident of the Dog in the Night-Time", "Mark Haddon", "Mystery", 2003),
    ("The Midnight Library", "Matt Haig", "Fantasy", 2020),
    ("The Shadow of the Wind", "Carlos Ruiz Zafon", "Mystery", 2001),
    ("The Unbearable Lightness of Being", "Milan Kundera", "Fiction", 1984),
    ("Blindness", "Jose Saramago", "Dystopian", 1995),
    ("The Master and Margarita", "Mikhail Bulgakov", "Fantasy", 1967),
    ("Steppenwolf", "Hermann Hesse", "Fiction", 1927),
    ("The Magic Mountain", "Thomas Mann", "Fiction", 1924),
    ("All Quiet on the Western Front", "Erich Maria Remarque", "Historical Fiction", 1929),
]

# Medium CSV: a 100-book import that makes progress notifications worth watching.
MEDIUM_CSV_BOOKS = [
    ("Jude the Obscure", "Thomas Hardy", "Fiction", 1895),
    ("Tess of the d'Urbervilles", "Thomas Hardy", "Fiction", 1891),
    ("Far from the Madding Crowd", "Thomas Hardy", "Fiction", 1874),
    ("Middlemarch", "George Eliot", "Fiction", 1871),
    ("Silas Marner", "George Eliot", "Fiction", 1861),
    ("Heart of Darkness", "Joseph Conrad", "Fiction", 1899),
    ("Lord Jim", "Joseph Conrad", "Adventure", 1900),
    ("The Time Machine", "H.G. Wells", "Science Fiction", 1895),
    ("The War of the Worlds", "H.G. Wells", "Science Fiction", 1898),
    ("The Invisible Man", "H.G. Wells", "Science Fiction", 1897),
    ("Twenty Thousand Leagues Under the Seas", "Jules Verne", "Adventure", 1870),
    ("Around the World in Eighty Days", "Jules Verne", "Adventure", 1872),
    ("Journey to the Center of the Earth", "Jules Verne", "Adventure", 1864),
    ("Robinson Crusoe", "Daniel Defoe", "Adventure", 1719),
    ("Gulliver's Travels", "Jonathan Swift", "Adventure", 1726),
    ("Don Quixote", "Miguel de Cervantes", "Fiction", 1605),
    ("The Sorrows of Young Werther", "Johann Wolfgang von Goethe", "Fiction", 1774),
    ("Madame Bovary", "Gustave Flaubert", "Fiction", 1856),
    ("Pere Goriot", "Honore de Balzac", "Fiction", 1835),
    ("Germinal", "Emile Zola", "Fiction", 1885),
    ("Fathers and Sons", "Ivan Turgenev", "Fiction", 1862),
    ("Dead Souls", "Nikolai Gogol", "Fiction", 1842),
    ("Doctor Zhivago", "Boris Pasternak", "Historical Fiction", 1957),
    (
        "One Day in the Life of Ivan Denisovich",
        "Aleksandr Solzhenitsyn",
        "Historical Fiction",
        1962,
    ),
    ("The Sound and the Fury", "William Faulkner", "Fiction", 1929),
    ("As I Lay Dying", "William Faulkner", "Fiction", 1930),
    ("Wise Blood", "Flannery O'Connor", "Fiction", 1952),
    ("The Heart Is a Lonely Hunter", "Carson McCullers", "Fiction", 1940),
    ("Rabbit, Run", "John Updike", "Fiction", 1960),
    ("American Pastoral", "Philip Roth", "Fiction", 1997),
    ("The Adventures of Augie March", "Saul Bellow", "Fiction", 1953),
    ("White Noise", "Don DeLillo", "Fiction", 1985),
    ("The Crying of Lot 49", "Thomas Pynchon", "Fiction", 1966),
    ("The Shipping News", "Annie Proulx", "Fiction", 1993),
    ("Housekeeping", "Marilynne Robinson", "Fiction", 1980),
    ("Angle of Repose", "Wallace Stegner", "Historical Fiction", 1971),
    ("Crossing to Safety", "Wallace Stegner", "Fiction", 1987),
    ("Cold Mountain", "Charles Frazier", "Historical Fiction", 1997),
    ("A Clockwork Orange", "Anthony Burgess", "Dystopian", 1962),
    ("The Quiet American", "Graham Greene", "Fiction", 1955),
    ("The Power and the Glory", "Graham Greene", "Fiction", 1940),
    ("Brideshead Revisited", "Evelyn Waugh", "Fiction", 1945),
    ("Lucky Jim", "Kingsley Amis", "Fiction", 1954),
    ("The Sea, the Sea", "Iris Murdoch", "Fiction", 1978),
    ("The Golden Notebook", "Doris Lessing", "Fiction", 1962),
    ("The Prime of Miss Jean Brodie", "Muriel Spark", "Fiction", 1961),
    ("NW", "Zadie Smith", "Fiction", 2012),
    ("High Fidelity", "Nick Hornby", "Fiction", 1995),
    ("Jonathan Strange & Mr Norrell", "Susanna Clarke", "Fantasy", 2004),
    ("Piranesi", "Susanna Clarke", "Fantasy", 2020),
    ("The Night Circus", "Erin Morgenstern", "Fantasy", 2011),
    ("Six of Crows", "Leigh Bardugo", "Young Adult", 2015),
    ("Shadow and Bone", "Leigh Bardugo", "Young Adult", 2012),
    ("The Golden Compass", "Philip Pullman", "Fantasy", 1995),
    ("The Subtle Knife", "Philip Pullman", "Fantasy", 1997),
    ("Sabriel", "Garth Nix", "Fantasy", 1995),
    ("Howl's Moving Castle", "Diana Wynne Jones", "Fantasy", 1986),
    ("The Amulet of Samarkand", "Jonathan Stroud", "Fantasy", 2003),
    ("Eragon", "Christopher Paolini", "Fantasy", 2002),
    ("Artemis Fowl", "Eoin Colfer", "Children", 2001),
    ("Inkheart", "Cornelia Funke", "Children", 2003),
    ("Stranger in a Strange Land", "Robert A. Heinlein", "Science Fiction", 1961),
    ("Starship Troopers", "Robert A. Heinlein", "Science Fiction", 1959),
    ("Ringworld", "Larry Niven", "Science Fiction", 1970),
    ("Ender's Game", "Orson Scott Card", "Science Fiction", 1985),
    ("Hyperion", "Dan Simmons", "Science Fiction", 1989),
    ("A Fire Upon the Deep", "Vernor Vinge", "Science Fiction", 1992),
    ("Revelation Space", "Alastair Reynolds", "Science Fiction", 2000),
    ("Consider Phlebas", "Iain M. Banks", "Science Fiction", 1987),
    ("Ancillary Justice", "Ann Leckie", "Science Fiction", 2013),
    ("Old Man's War", "John Scalzi", "Science Fiction", 2005),
    ("The Long Way to a Small, Angry Planet", "Becky Chambers", "Science Fiction", 2014),
    ("Children of Time", "Adrian Tchaikovsky", "Science Fiction", 2015),
    ("Leviathan Wakes", "James S.A. Corey", "Science Fiction", 2011),
    ("Red Rising", "Pierce Brown", "Science Fiction", 2014),
    ("The Blade Itself", "Joe Abercrombie", "Fantasy", 2006),
    ("The Lies of Locke Lamora", "Scott Lynch", "Fantasy", 2006),
    ("Tigana", "Guy Gavriel Kay", "Fantasy", 1990),
    ("The Eye of the World", "Robert Jordan", "Fantasy", 1990),
    ("The Exorcist", "William Peter Blatty", "Horror", 1971),
    ("Rosemary's Baby", "Ira Levin", "Horror", 1967),
    ("The Andromeda Strain", "Michael Crichton", "Science Fiction", 1969),
    ("Jurassic Park", "Michael Crichton", "Science Fiction", 1990),
    ("The Hunt for Red October", "Tom Clancy", "Thriller", 1984),
    ("Raise the Titanic!", "Clive Cussler", "Adventure", 1976),
    ("Watchers", "Dean Koontz", "Horror", 1987),
    ("Coma", "Robin Cook", "Thriller", 1977),
    ("The Firm", "John Grisham", "Thriller", 1991),
    ("A Time to Kill", "John Grisham", "Thriller", 1989),
    ("Presumed Innocent", "Scott Turow", "Thriller", 1987),
    ("Absolute Power", "David Baldacci", "Thriller", 1996),
    ("The Bone Collector", "Jeffery Deaver", "Thriller", 1997),
    ("A Is for Alibi", "Sue Grafton", "Mystery", 1982),
    ("Indemnity Only", "Sara Paretsky", "Mystery", 1982),
    ("One for the Money", "Janet Evanovich", "Mystery", 1994),
    ("Devil in a Blue Dress", "Walter Mosley", "Mystery", 1990),
    ("L.A. Confidential", "James Ellroy", "Mystery", 1990),
    ("Mystic River", "Dennis Lehane", "Mystery", 2001),
    ("Gone, Baby, Gone", "Dennis Lehane", "Mystery", 1998),
    ("Faceless Killers", "Henning Mankell", "Mystery", 1991),
    ("The Snowman", "Jo Nesbo", "Thriller", 2007),
    ("The Devotion of Suspect X", "Keigo Higashino", "Mystery", 2005),
    ("Big Little Lies", "Liane Moriarty", "Fiction", 2014),
    ("My Sister's Keeper", "Jodi Picoult", "Fiction", 2004),
    ("The Forgotten Garden", "Kate Morton", "Mystery", 2008),
    ("The Thirteenth Tale", "Diane Setterfield", "Mystery", 2006),
    ("In a Dark, Dark Wood", "Ruth Ware", "Thriller", 2015),
    ("The Guest List", "Lucy Foley", "Thriller", 2020),
    ("The Quiet Tenant", "Clemence Michallon", "Thriller", 2023),
    ("Tell No One", "Harlan Coben", "Thriller", 2001),
    ("Magpie Murders", "Anthony Horowitz", "Mystery", 2016),
    ("In Cold Blood", "Truman Capote", "True Crime", 1966),
    ("The Year of Magical Thinking", "Joan Didion", "Memoir", 2005),
    ("The Orchid Thief", "Susan Orlean", "True Crime", 1998),
    ("Midnight in the Garden of Good and Evil", "John Berendt", "True Crime", 1994),
    ("Quiet: The Power of Introverts", "Susan Cain", "Psychology", 2012),
    ("The Power of Habit", "Charles Duhigg", "Psychology", 2012),
    ("Grit", "Angela Duckworth", "Psychology", 2016),
    ("Mindset", "Carol Dweck", "Psychology", 2006),
    ("Give and Take", "Adam Grant", "Business", 2013),
    ("Essentialism", "Greg McKeown", "Self-Help", 2014),
    ("Factfulness", "Hans Rosling", "Science", 2018),
    ("The Better Angels of Our Nature", "Steven Pinker", "History", 2011),
    ("Guns, Germs, and Steel", "Jared Diamond", "History", 1997),
    ("An Immense World", "Ed Yong", "Science", 2022),
    ("Entangled Life", "Merlin Sheldrake", "Science", 2020),
    ("Braiding Sweetgrass", "Robin Wall Kimmerer", "Science", 2013),
    ("Silent Spring", "Rachel Carson", "Science", 1962),
    ("A Sand County Almanac", "Aldo Leopold", "Science", 1949),
    ("The Professor and the Madman", "Simon Winchester", "History", 1998),
    ("The River of Doubt", "Candice Millard", "History", 2005),
    ("In the Heart of the Sea", "Nathaniel Philbrick", "History", 2000),
    ("Ghost Soldiers", "Hampton Sides", "History", 2001),
    ("Empire of the Summer Moon", "S.C. Gwynne", "History", 2010),
    ("The Worst Hard Time", "Timothy Egan", "History", 2006),
    ("The Warmth of Other Suns", "Isabel Wilkerson", "History", 2010),
    ("Between the World and Me", "Ta-Nehisi Coates", "Memoir", 2015),
    ("Just Mercy", "Bryan Stevenson", "Memoir", 2014),
    ("Evicted", "Matthew Desmond", "History", 2016),
    ("Nickel and Dimed", "Barbara Ehrenreich", "History", 2001),
]


def _rows_for(books: list[tuple[str, str, str, int]], used: set[str]) -> list[dict]:
    rows = []
    for i, (title, author, genre, year) in enumerate(books):
        copies = (i % 4) + 1
        rows.append(
            {
                "isbn": isbn13_for(title, author, used),
                "title": title,
                "author_name": author,
                "genre": genre,
                "publication_year": year,
                "available_copies": copies,
            }
        )
    return rows


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()

    csv_rows = _rows_for(SAMPLE_CSV_BOOKS, used)
    medium_rows = _rows_for(MEDIUM_CSV_BOOKS, used)
    json_rows = _rows_for(SAMPLE_JSON_BOOKS, used)

    fieldnames = ["isbn", "title", "author_name", "genre", "publication_year", "available_copies"]
    for name, rows in (("books_sample.csv", csv_rows), ("books_medium.csv", medium_rows)):
        with (SAMPLES_DIR / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows):>3} books -> {name}")

    # JSON variant demonstrates optional total_copies on a few entries.
    for i, row in enumerate(json_rows):
        if i % 3 == 0:
            row["total_copies"] = row["available_copies"] + 1
    with (SAMPLES_DIR / "books_sample.json").open("w", encoding="utf-8") as f:
        json.dump(json_rows, f, indent=2)
        f.write("\n")
    print(f"wrote {len(json_rows):>3} books -> books_sample.json")


if __name__ == "__main__":
    main()
