"""
Seed lightweight NCERT chapter metadata for demo classes 3-8.

Data goes into `curriculum_chapters` so the existing ncert router (which now
merges curriculum_chapters + ncert_textbooks) picks it up automatically.

Skipped:
  - Class 6 Science / Social Sciences (already in ncert_textbooks)
  - Class 7 (already fully in curriculum_chapters)

Seeded:
  - Class 3, 4, 5: Maths, English, EVS (NCERT scheme for these grades)
  - Class 6: Maths, English only (Science + Social already in ncert_textbooks)
  - Class 8: Maths, Science, English, Social Science

Re-run safe: upserts by chapter_key.

Usage:
    venv/bin/python tests/seed_demo_classes_3_to_8.py            # dry run
    venv/bin/python tests/seed_demo_classes_3_to_8.py --execute  # write
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

# ---------------------------------------------------------------------------
# Curriculum content (concise, NCERT-aligned chapter titles + 3-4 concepts each)
# ---------------------------------------------------------------------------

# Structure: SEED[class_no][subject] = [(chapter_title, [concept_name, ...]), ...]
SEED = {
    3: {
        "Maths": [
            ("What is Long, What is Round?", ["Shapes around us", "Long vs round objects", "Comparing sizes"]),
            ("Fun with Numbers", ["Counting beyond 100", "Place value", "Number names"]),
            ("Give and Take", ["Addition stories", "Subtraction stories", "Word problems"]),
            ("Long and Short", ["Measuring length", "Standard and non-standard units", "Estimating lengths"]),
            ("Shapes and Designs", ["2D shapes", "Patterns", "Tiling designs"]),
            ("Fun with Give and Take", ["Mental addition", "Mental subtraction", "Money problems"]),
            ("Time Goes On", ["Reading a clock", "Days and months", "Calendar reading"]),
            ("Who is Heavier?", ["Comparing weights", "Using a balance", "Standard units of mass"]),
        ],
        "English": [
            ("Good Morning", ["Greetings and politeness", "Rhyming words", "Reading aloud"]),
            ("The Magic Garden", ["Story reading", "New vocabulary", "Picture comprehension"]),
            ("Bird Talk", ["Sounds of birds", "Onomatopoeia", "Recitation"]),
            ("Nina and the Baby Sparrows", ["Empathy with animals", "Story sequencing", "Describing characters"]),
            ("Little by Little", ["Growth and change", "Verbs of action", "Self description"]),
            ("The Enormous Turnip", ["Cooperation", "Cumulative tale", "Predicting events"]),
            ("My Silly Sister", ["Family vocabulary", "Adjectives", "Narrative writing"]),
            ("He is My Brother", ["Compassion", "Asking and answering", "Sentence formation"]),
        ],
        "EVS": [
            ("Poonam's Day Out", ["Animals around us", "Their homes", "Their movements"]),
            ("The Plant Fairy", ["Plants around us", "Leaves and stems", "Plant uses"]),
            ("Water O' Water!", ["Sources of water", "Water in daily life", "Saving water"]),
            ("Our First School", ["Family as first teachers", "Learning at home", "Members of a family"]),
            ("Chhotu's House", ["Types of houses", "Materials used", "Shelter and safety"]),
            ("Foods We Eat", ["Food groups", "Cooked vs raw", "Food from plants and animals"]),
            ("Saying without Speaking", ["Sign language basics", "Expressions", "Body language"]),
            ("Flying High", ["Birds and flight", "Insects that fly", "Things humans use to fly"]),
        ],
    },
    4: {
        "Maths": [
            ("Building with Bricks", ["Patterns in walls", "3D shapes", "Geometric arrangement"]),
            ("Long and Short", ["Metres and centimetres", "Conversions", "Estimating long distances"]),
            ("A Trip to Bhopal", ["Larger numbers", "Number sense", "Real-world counting"]),
            ("Tick-Tick-Tick", ["Hours, minutes, seconds", "12-hour and 24-hour time", "Duration problems"]),
            ("The Way the World Looks", ["Maps and views", "Top, side, front views", "Spatial reasoning"]),
            ("The Junk Seller", ["Multiplication tables", "Multiplication strategies", "Word problems"]),
            ("Jugs and Mugs", ["Measuring volume", "Litres and millilitres", "Capacity comparison"]),
            ("Carts and Wheels", ["Circles and curves", "Wheels in real life", "Drawing circles"]),
            ("Halves and Quarters", ["Fractions of a whole", "Equal parts", "Sharing equally"]),
            ("Play with Patterns", ["Number patterns", "Shape patterns", "Symmetry basics"]),
        ],
        "English": [
            ("Wake Up!", ["Morning routines", "Verbs", "Rhyme and rhythm"]),
            ("Noses", ["Body parts", "Describing words", "Funny imagery"]),
            ("Run!", ["Action verbs", "Sequencing", "Picture comprehension"]),
            ("The Little Fir Tree", ["Story moral", "Seasons in stories", "Character feelings"]),
            ("Anything Can Happen", ["Fantasy and imagination", "Story prediction", "Creative writing"]),
            ("Don't Be Afraid of the Dark", ["Fear and courage", "Rhyme scheme", "Self-expression"]),
            ("Hiawatha", ["Nature poetry", "Cultural stories", "Recitation"]),
            ("A Watering Rhyme", ["Plant care", "Imperative sentences", "Rhyming couplets"]),
        ],
        "EVS": [
            ("Going to School", ["Modes of transport", "Distance and journey", "Diverse experiences"]),
            ("Ear to Ear", ["Hearing and sound", "Animal ears", "Communication"]),
            ("A Day with Nandu", ["Elephants and habitat", "Animal families", "Conservation"]),
            ("The Story of Amrita", ["Tree conservation", "Bishnoi community", "Caring for nature"]),
            ("Anita and the Honeybees", ["Bees and honey", "Pollination", "Livelihoods from nature"]),
            ("Omana's Journey", ["Travel by train", "Indian geography", "Observation skills"]),
            ("From the Window", ["Observing surroundings", "Changes outside", "Note-keeping"]),
            ("Reaching Grandmother's House", ["Maps and directions", "Travel modes", "Family connections"]),
        ],
    },
    5: {
        "Maths": [
            ("The Fish Tale", ["Large numbers", "Multiplication in context", "Comparing quantities"]),
            ("Shapes and Angles", ["Angles around us", "Acute, right, obtuse", "Measuring angles"]),
            ("How Many Squares?", ["Area concept", "Counting unit squares", "Perimeter vs area"]),
            ("Parts and Wholes", ["Fractions of shapes", "Equivalent fractions", "Fractions of quantities"]),
            ("Does it Look the Same?", ["Symmetry", "Mirror images", "Patterns"]),
            ("Be My Multiple, I'll Be Your Factor", ["Multiples and factors", "Common factors", "Prime numbers intro"]),
            ("Can You See the Pattern?", ["Number patterns", "Geometric patterns", "Pattern rules"]),
            ("Mapping Your Way", ["Reading maps", "Scale", "Directions"]),
            ("Boxes and Sketches", ["Nets of solids", "3D to 2D", "Visualising shapes"]),
            ("Tenths and Hundredths", ["Decimal numbers", "Place value of decimals", "Money as decimals"]),
        ],
        "English": [
            ("Ice-Cream Man", ["Summer scenes", "Sensory words", "Rhyme"]),
            ("Wonderful Waste!", ["Story moral", "Resourcefulness", "Vocabulary in context"]),
            ("Bamboo Curry", ["Cultural foods", "Procedure text", "Sequencing"]),
            ("Teamwork", ["Cooperation", "Action verbs", "Group work"]),
            ("Flying Together", ["Wisdom in stories", "Animal fables", "Moral lessons"]),
            ("My Shadow", ["Observation poems", "Pronouns", "Imagery"]),
            ("Crying", ["Emotions", "Adjectives", "Reflective writing"]),
            ("The Lazy Frog", ["Personification", "Humour in poetry", "Rhyming words"]),
        ],
        "EVS": [
            ("Super Senses", ["Animal senses", "Human senses", "Survival in nature"]),
            ("A Snake Charmer's Story", ["Communities and livelihoods", "Snakes", "Changing professions"]),
            ("From Tasting to Digesting", ["Digestive system", "Taste buds", "Healthy eating"]),
            ("Mangoes Round the Year", ["Food preservation", "Seasonal foods", "Storage methods"]),
            ("Seeds and Seeds", ["Seed dispersal", "Germination", "Plant life cycle"]),
            ("Every Drop Counts", ["Water harvesting", "Wells and ponds", "Saving water"]),
            ("Experiments with Water", ["Floating and sinking", "Dissolving", "Properties of water"]),
            ("A Treat for Mosquitoes", ["Disease and prevention", "Hygiene", "Public health"]),
            ("Up You Go!", ["Mountains and climbing", "Adventure stories", "Safety in nature"]),
            ("Walls Tell Stories", ["Forts and monuments", "Indian history", "Architecture"]),
        ],
    },
    6: {
        # Science and Social Sciences for Class 6 are already in ncert_textbooks
        "Maths": [
            ("Patterns in Mathematics", ["Number sequences", "Visual patterns", "Generalising rules"]),
            ("Lines and Angles", ["Types of lines", "Angle measurement", "Pairs of angles"]),
            ("Number Play", ["Patterns with digits", "Smallest and largest", "Number games"]),
            ("Data Handling and Presentation", ["Bar graphs", "Pictographs", "Data collection"]),
            ("Prime Time", ["Primes and composites", "Sieve of Eratosthenes", "Co-prime numbers"]),
            ("Perimeter and Area", ["Perimeter of polygons", "Area of rectangles", "Area in real life"]),
            ("Fractions", ["Like and unlike fractions", "Equivalent fractions", "Fraction operations"]),
            ("Playing with Constructions", ["Compass and ruler", "Constructing triangles", "Bisectors"]),
            ("Symmetry", ["Line symmetry", "Rotational symmetry", "Symmetric patterns"]),
            ("The Other Side of Zero", ["Negative numbers", "Number line", "Integer operations"]),
        ],
        "English": [
            ("A Bottle of Dew", ["Observation in nature", "Descriptive writing", "Imagery"]),
            ("The Unsung Heroes", ["Everyday heroes", "Biography writing", "Gratitude"]),
            ("A Homage to Our Brave Soldiers", ["Patriotism", "Speech writing", "Vocabulary of valour"]),
            ("The Winding Up", ["Story closure", "Plot review", "Reflective writing"]),
            ("Hanuman: Symbol of Courage and Energy", ["Cultural narratives", "Character analysis", "Mythology"]),
            ("Sons of Earth", ["Indian farmers", "Rural life", "Empathy"]),
            ("The Friendly Mongoose", ["Animal stories", "Cause and effect", "Moral lessons"]),
            ("The Shepherd's Treasure", ["Wisdom over wealth", "Folk tales", "Lesson identification"]),
        ],
    },
    8: {
        "Maths": [
            ("Rational Numbers", ["Properties of rational numbers", "Representation on number line", "Operations"]),
            ("Linear Equations in One Variable", ["Solving equations", "Word problems", "Applications"]),
            ("Understanding Quadrilaterals", ["Polygon properties", "Types of quadrilaterals", "Angle sum"]),
            ("Data Handling", ["Bar graphs", "Pie charts", "Probability basics"]),
            ("Squares and Square Roots", ["Perfect squares", "Square roots by factorisation", "Patterns"]),
            ("Cubes and Cube Roots", ["Perfect cubes", "Cube roots", "Hardy-Ramanujan numbers"]),
            ("Comparing Quantities", ["Ratios and percentages", "Profit and loss", "Simple and compound interest"]),
            ("Algebraic Expressions and Identities", ["Terms and coefficients", "Identities", "Multiplication of expressions"]),
            ("Mensuration", ["Area of trapezium", "Surface area of solids", "Volume of cuboids"]),
            ("Exponents and Powers", ["Negative exponents", "Laws of exponents", "Standard form"]),
            ("Direct and Inverse Proportions", ["Direct variation", "Inverse variation", "Word problems"]),
            ("Factorisation", ["Common factors", "Factorising trinomials", "Division of polynomials"]),
        ],
        "Science": [
            ("Crop Production and Management", ["Agricultural practices", "Irrigation", "Storage of grains"]),
            ("Microorganisms: Friend and Foe", ["Types of microbes", "Useful microorganisms", "Diseases caused"]),
            ("Coal and Petroleum", ["Fossil fuels", "Natural resources", "Conservation"]),
            ("Combustion and Flame", ["Combustion types", "Structure of flame", "Fuels"]),
            ("Conservation of Plants and Animals", ["Biodiversity", "Endangered species", "Sanctuaries"]),
            ("Cell - Structure and Functions", ["Cell organelles", "Plant vs animal cells", "Discovery of cell"]),
            ("Reproduction in Animals", ["Sexual reproduction", "Internal vs external", "Life cycles"]),
            ("Reaching the Age of Adolescence", ["Puberty changes", "Hormones", "Reproductive health"]),
            ("Force and Pressure", ["Types of forces", "Pressure in fluids", "Atmospheric pressure"]),
            ("Friction", ["Causes of friction", "Reducing friction", "Friction in daily life"]),
            ("Sound", ["Production of sound", "Wave properties", "Noise pollution"]),
            ("Chemical Effects of Electric Current", ["Conduction in liquids", "Electroplating", "Safety"]),
        ],
        "English": [
            ("The Best Christmas Present in the World", ["Story analysis", "Themes of war and peace", "Letter writing"]),
            ("The Tsunami", ["Natural disasters", "Survival narratives", "Reading non-fiction"]),
            ("Glimpses of the Past", ["Indian history", "Comic-style narrative", "Cause and effect"]),
            ("Bepin Choudhury's Lapse of Memory", ["Mystery genre", "Character motivation", "Plot twists"]),
            ("The Summit Within", ["Mountaineering", "Reflective writing", "Inner journey"]),
            ("This is Jody's Fawn", ["Empathy with animals", "Story climax", "Descriptive passages"]),
            ("A Visit to Cambridge", ["Travel writing", "Inspiring people", "Disability and ability"]),
            ("A Short Monsoon Diary", ["Diary writing", "Observation of nature", "Mood in writing"]),
        ],
        "Social Science": [
            ("Resources", ["Types of resources", "Sustainable development", "Resource conservation"]),
            ("Land, Soil, Water, Natural Vegetation and Wildlife Resources", ["Land use", "Soil types", "Conservation strategies"]),
            ("Mineral and Power Resources", ["Types of minerals", "Conventional vs non-conventional", "Energy use"]),
            ("Agriculture", ["Farming systems", "Major crops", "Agricultural practices"]),
            ("How When and Where", ["Periodisation of history", "Sources of modern history", "Maps and dates"]),
            ("From Trade to Territory", ["East India Company", "Battle of Plassey", "Subsidiary alliance"]),
            ("Ruling the Countryside", ["Permanent Settlement", "Indigo cultivation", "Peasant resistance"]),
            ("The Indian Constitution", ["Constitutional principles", "Fundamental rights", "Separation of powers"]),
            ("Understanding Secularism", ["Secular state", "Religious freedom", "Indian secularism"]),
            ("Why Do We Need a Parliament", ["Role of Parliament", "Lok Sabha and Rajya Sabha", "Lawmaking"]),
        ],
    },
}

# Book codes are placeholder identifiers — only used to disambiguate chapter_key.
BOOK_CODE = {
    ("Maths", 3): "demaths3", ("English", 3): "deeng3", ("EVS", 3): "deevs3",
    ("Maths", 4): "demaths4", ("English", 4): "deeng4", ("EVS", 4): "deevs4",
    ("Maths", 5): "demaths5", ("English", 5): "deeng5", ("EVS", 5): "deevs5",
    ("Maths", 6): "demaths6", ("English", 6): "deeng6",
    ("Maths", 8): "demaths8", ("Science", 8): "desci8", ("English", 8): "deeng8", ("Social Science", 8): "desoc8",
}

SUBJECT_PREFIX = {
    "Maths": "maths",
    "English": "english",
    "EVS": "evs",
    "Science": "science",
    "Social Science": "social",
}


def chapter_key(subject: str, class_no: int, ch_num: int) -> str:
    book = BOOK_CODE.get((subject, class_no), f"de{SUBJECT_PREFIX.get(subject, subject.lower())}{class_no}")
    return f"{SUBJECT_PREFIX[subject]}_{book}_ch{ch_num:02d}"


def build_documents() -> list:
    now = datetime.now(timezone.utc)
    docs = []
    for class_no, by_subject in SEED.items():
        for subject, chapters in by_subject.items():
            for idx, (title, concepts) in enumerate(chapters, start=1):
                key = chapter_key(subject, class_no, idx)
                concept_docs = [
                    {
                        "concept_id": f"{SUBJECT_PREFIX[subject]}{class_no}_ch{idx}_c{i}",
                        "name": name,
                        "description": f"Foundational understanding of {name.lower()} in the context of {title}.",
                    }
                    for i, name in enumerate(concepts, start=1)
                ]
                docs.append({
                    "chapter_key": key,
                    "board": "NCERT",
                    "class": class_no,
                    "subject": subject,
                    "book_code": BOOK_CODE.get((subject, class_no), f"de{SUBJECT_PREFIX.get(subject, subject.lower())}{class_no}"),
                    "chapter_number": idx,
                    "chapter_title": title,
                    "learning_objectives": [f"Understand {c['name']}" for c in concept_docs],
                    "concepts": concept_docs,
                    "chapter_summary": f"{title} introduces students to the core ideas of {', '.join(c['name'] for c in concept_docs)}.",
                    "key_formulas_or_rules": [],
                    "real_world_connections": [],
                    "exercises_preserved": [],
                    "activities_preserved": [],
                    "demo_seed": True,
                    "created_at": now,
                    "updated_at": now,
                })
    return docs


async def run(execute: bool):
    docs = build_documents()
    print(f"Built {len(docs)} chapter docs across "
          f"{len({(d['class'], d['subject']) for d in docs})} class+subject pairs.\n")

    by_class = {}
    for d in docs:
        by_class.setdefault(d["class"], {}).setdefault(d["subject"], 0)
        by_class[d["class"]][d["subject"]] += 1
    for c in sorted(by_class):
        print(f"  Class {c}: " + ", ".join(f"{s}={n}" for s, n in sorted(by_class[c].items())))

    if not execute:
        print("\n[DRY RUN] No data written. Pass --execute to write.")
        return

    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"), tls=True, tlsCAFile=certifi.where())
    db = client[os.getenv("MONGODB_DB", "mymedha_dev")]
    col = db["curriculum_chapters"]

    inserted = 0
    updated = 0
    for d in docs:
        result = await col.update_one(
            {"chapter_key": d["chapter_key"]},
            {
                "$set": {k: v for k, v in d.items() if k != "created_at"},
                "$setOnInsert": {"created_at": d["created_at"]},
            },
            upsert=True,
        )
        if result.upserted_id:
            inserted += 1
        else:
            updated += 1

    client.close()
    print(f"\nDone. inserted={inserted}  updated={updated}  total={inserted + updated}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Write to DB (default: dry run)")
    args = ap.parse_args()
    asyncio.run(run(args.execute))
