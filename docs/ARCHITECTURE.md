# MyMedha LXP — Architecture & Flow

## Product Vision

> "We don't replace the teacher. We reinforce what the teacher taught, adapted to each student's pace."

MyMedha is an AI-powered learning platform for Class 3-9 students that captures classroom teaching, grounds it with textbook content, and delivers personalized revision experiences.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                          │
│                                                              │
│   📚 NCERT Textbook          🎙️ Teacher's Classroom         │
│   (curriculum_chapters)       (audio → transcript)           │
│                                                              │
│   Seeded via                  Recorded → Azure Speech →      │
│   seed_curriculum.py          daily_transcripts collection   │
└──────────────┬──────────────────────┬───────────────────────┘
               │                      │
               ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM PROCESSING LAYER                      │
│                    (Azure OpenAI)                             │
│                                                              │
│   ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│   │   Summary    │  │   Widget     │  │   Story          │  │
│   │   Generator  │  │   Generator  │  │   Generator      │  │
│   │             │  │              │  │                  │  │
│   │ Textbook +  │  │ Curriculum → │  │ Summary +        │  │
│   │ Transcript →│  │ Interactive  │  │ Persona →        │  │
│   │ JSON Blocks │  │ Widget JSON  │  │ Narrative +      │  │
│   │             │  │              │  │ Widgets +        │  │
│   │ Structured  │  │ slider /     │  │ Flashcards +     │  │
│   │ Output with │  │ drag /       │  │ Mind Map         │  │
│   │ Validation  │  │ step_builder │  │                  │  │
│   └─────────────┘  └──────────────┘  └──────────────────┘  │
│                                                              │
│   STRICT RULE: LLM uses ONLY provided sources.               │
│   No external knowledge. Grounded in teacher + textbook.     │
└──────────────┬──────────────────────┬───────────────────────┘
               │                      │
               ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      MONGODB STORAGE                         │
│                                                              │
│   classes_daily {                                            │
│     tenant, date, class_no, section, subject,                │
│     topics: [...],                                           │
│     summary: "legacy markdown",                              │
│     summary_blocks: [ structured JSON blocks ],              │
│     try_it_widget: { widget JSON },                          │
│   }                                                          │
│                                                              │
│   curriculum_chapters    → textbook data (seeded)            │
│   student_daily_progress → per-student tracking              │
│   daily_transcripts      → teacher audio transcripts         │
│   student_daily_summary  → pipeline-generated summaries      │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND                          │
│                                                              │
│   GET  /api/classes/daily          → list daily classes      │
│   POST /api/classes/daily/test-summary → generate summary    │
│   POST /api/classes/daily/generate-widget → generate widget  │
│   POST /api/ai/story               → generate story          │
│   POST /api/ai/chat                → AI tutor chat            │
│   GET  /api/daily-quiz/...         → quiz endpoints           │
│   POST /api/progress/track         → track student activity   │
│   GET  /api/leaderboard/...        → gamification             │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                    REACT FRONTEND                            │
│                    (Vite + Tailwind)                          │
│                                                              │
│   StudentDashboard → ClassDetailView → 5 Independent Tabs    │
└─────────────────────────────────────────────────────────────┘
```

---

## Student Learning Flow

```
Student logs in → Dashboard shows today's classes
                          │
                          ▼
              ┌─── Clicks a class ───┐
              │                      │
              ▼                      │
   ┌──────────────────────┐          │
   │  📖 SUMMARY TAB      │          │
   │  (Block-based UI)     │          │
   │                       │          │
   │  ┌─ ConceptCard ───┐ │          │
   │  │ Core explanation │ │          │
   │  └─────────────────┘ │          │
   │  ┌─ TermsChips ────┐ │          │
   │  │ Tappable vocab   │ │          │
   │  └─────────────────┘ │          │
   │  ┌─ StepFlow ──────┐ │          │
   │  │ Process steps    │ │          │
   │  └─────────────────┘ │          │
   │  ┌─ AnalogyBubble ─┐ │          │
   │  │ Memory trick     │ │          │
   │  └─────────────────┘ │          │
   │           │           │          │
   │           ▼           │          │
   │  ┌─ QuickCheck ────┐ │          │
   │  │ 3 checkpoint Qs │ │          │
   │  │ (from same data)│ │          │
   │  └───────┬─────────┘ │          │
   │          │            │          │
   └──────────┼────────────┘          │
              │                       │
              ▼                       │
   ┌──── ADAPTIVE PATH ────┐         │
   │  Score determines      │         │
   │  recommended next step │         │
   │                        │         │
   │  0-1/3: "Strengthen"   │         │
   │  ├─ Re-read Summary    │         │
   │  └─ Flashcards         │         │
   │                        │         │
   │  2/3: "Reinforce"      │         │
   │  ├─ Story Mode         │         │
   │  ├─ Flashcards         │         │
   │  └─ Try It Yourself    │         │
   │                        │         │
   │  3/3: "Challenge"      │         │
   │  ├─ Try It Yourself    │         │
   │  └─ Take Full Quiz     │         │
   └────────┬───────────────┘         │
            │                          │
            ▼                          │
   Student clicks recommended action   │
            │                          │
     ┌──────┴──────┬──────────┬───────┤
     ▼             ▼          ▼       ▼
┌─────────┐ ┌──────────┐ ┌──────┐ ┌──────┐
│📖 STORY │ │🃏 FLASH- │ │🧪 TRY│ │🏆QUIZ│
│  TAB    │ │  CARDS   │ │  IT  │ │ TAB  │
│         │ │  TAB     │ │  TAB │ │      │
│Generate │ │          │ │      │ │ MCQ  │
│narrative│ │FlipCards │ │Slider│ │ Auto │
│with     │ │with      │ │Drag  │ │graded│
│character│ │confidence│ │Step  │ │ XP   │
│         │ │rating    │ │Build │ │earned│
│ → End   │ │          │ │      │ │      │
│   Card: │ │MindMap   │ │      │ │      │
│  ├ TryIt│ │(auto from│ │      │ │      │
│  ├ Flip │ │ terms)   │ │      │ │      │
│  ├ Mind │ │          │ │      │ │      │
│  └ Quiz │ │          │ │      │ │      │
└─────────┘ └──────────┘ └──────┘ └──────┘

   ALL TABS ARE INDEPENDENT
   Same source content, different engagement modes
```

---

## Summary Block Architecture (JSON, not Markdown)

```
LLM generates structured JSON → Frontend renders block components

┌───────────────────────────────────────────────────────┐
│  LLM Output (response_format: json_object)            │
│                                                        │
│  {                                                     │
│    "blocks": [                                         │
│      { "type": "concept",    ... },  → ConceptCard     │
│      { "type": "terms",      ... },  → TermsChips      │
│      { "type": "steps",      ... },  → StepFlow        │
│      { "type": "formula",    ... },  → FormulaBox      │
│      { "type": "fact",       ... },  → FactBullets     │
│      { "type": "analogy",    ... },  → AnalogyBubble   │
│      { "type": "checkpoint", ... },  → QuickCheck      │
│    ]                                                    │
│  }                                                     │
│                                                        │
│  Validated → Fallback to curriculum if LLM fails       │
└───────────────────────────────────────────────────────┘

Block Types by Subject:
┌─────────────┬─────────┬───────┬────────┬─────────┐
│ Block Type  │ Science │ Math  │ Social │ English │
├─────────────┼─────────┼───────┼────────┼─────────┤
│ concept     │   ✅    │  ✅   │   ✅   │   ✅    │
│ terms       │   ✅    │  ✅   │   ✅   │   ✅    │
│ steps       │   ✅    │  ✅   │   -    │   -     │
│ formula     │   ✅    │  ✅   │   -    │   -     │
│ fact        │   ✅    │  -    │   ✅   │   ✅    │
│ timeline    │   -     │  -    │   ✅   │   -     │
│ rule        │   -     │  ✅   │   -    │   ✅    │
│ analogy     │   ✅    │  ✅   │   ✅   │   ✅    │
│ checkpoint  │   ✅    │  ✅   │   ✅   │   ✅    │
└─────────────┴─────────┴───────┴────────┴─────────┘
```

---

## Personalization: Same Content, Different Doors

```
                ONE SOURCE OF TRUTH
        (Teacher's class + NCERT Textbook)
                      │
    ┌─────────────────┼─────────────────────┐
    │                 │                     │
    ▼                 ▼                     ▼
 REMEMBER          UNDERSTAND             APPLY
    │                 │                     │
    ▼                 ▼                     ▼
┌────────┐    ┌────────────┐    ┌───────────────┐
│Summary │    │   Story    │    │ Try It Yourself│
│(read)  │    │  (feel)    │    │   (do)         │
└────────┘    └────────────┘    └───────────────┘
┌────────┐                      ┌───────────────┐
│Flashcard│                     │     Quiz      │
│(recall) │                     │   (master)    │
└────────┘                      └───────────────┘

Personalization is NOT in WHAT they learn
but in HOW MUCH and WHICH MODE:

┌────────────────────────────────────────────────┐
│  Quick Check Score    →    Recommended Path    │
│                                                │
│  0-1 / 3 (Low)       →    Summary + Flashcards│
│  2 / 3   (Mid)       →    Story + Try It      │
│  3 / 3   (High)      →    Try It + Quiz       │
│                                                │
│  Same data. Different journey.                 │
└────────────────────────────────────────────────┘
```

---

## Class-Level Adaptation

```
┌──────────────────────────────────────────────────────┐
│                                                       │
│  Class 3-5:                                           │
│  ├─ Simple everyday words                             │
│  ├─ Max 3 key terms, Max 3 steps                      │
│  ├─ No formulas                                       │
│  └─ More analogies, simpler checkpoint questions      │
│                                                       │
│  Class 6-7:                                           │
│  ├─ Simple scientific vocabulary                      │
│  ├─ Max 5 key terms, Max 5 steps                      │
│  ├─ Basic formulas                                    │
│  └─ Mixed question types in checkpoint                │
│                                                       │
│  Class 8-9:                                           │
│  ├─ Standard scientific terminology                   │
│  ├─ Concise definitions                               │
│  ├─ Full formulas with notes                          │
│  └─ Higher difficulty in checkpoint & quiz            │
│                                                       │
│  Controlled via prompt parameter, not code change.    │
└──────────────────────────────────────────────────────┘
```

---

## Try It Yourself — Widget Types

```
┌──────────────────────────────────────────────────────┐
│  Widget Type          │  Best For         │ Example  │
├───────────────────────┼───────────────────┼──────────┤
│  slider_simulation    │  Math/Physics     │ Change   │
│                       │  formulas         │ radius,  │
│                       │                   │ see area │
├───────────────────────┼───────────────────┼──────────┤
│  parameter_simulation │  Physics cause-   │ F=ma     │
│                       │  effect           │ sliders  │
├───────────────────────┼───────────────────┼──────────┤
│  drag_sequence        │  Science/History  │ Order    │
│                       │  processes        │ water    │
│                       │                   │ cycle    │
├───────────────────────┼───────────────────┼──────────┤
│  step_builder         │  Math/Grammar     │ Solve    │
│                       │  problem solving  │ equation │
│                       │                   │ step by  │
│                       │                   │ step     │
└──────────────────────────────────────────────────────┘

LLM chooses the best widget type based on subject + topic.
Fallback: drag_sequence from curriculum concepts.
```

---

## Data Pipeline (Production Flow)

```
┌─────────────────────────────────────────────────────┐
│  1. CLASSROOM                                        │
│     Teacher teaches → Audio recorded via app          │
│                                                      │
│  2. TRANSCRIPTION                                    │
│     Audio → Azure Speech → daily_transcripts (MongoDB)│
│                                                      │
│  3. TOPIC IDENTIFICATION                             │
│     Transcript snippet → LLM → { chapter, topic }    │
│     Matched against curriculum_chapters               │
│                                                      │
│  4. SUMMARY GENERATION                               │
│     Transcript + NCERT context → LLM → JSON blocks   │
│     Validated → Stored in classes_daily               │
│                                                      │
│  5. WIDGET GENERATION                                │
│     Curriculum concepts → LLM → Widget JSON           │
│     Stored in classes_daily.try_it_widget              │
│                                                      │
│  6. STUDENT ACCESSES                                 │
│     Dashboard → Class → Summary → Quick Check →       │
│     Adaptive Path → Story / Flashcards / Try It / Quiz│
│                                                      │
│  7. PROGRESS TRACKING                                │
│     summary_viewed, quiz_score, streak, XP, badges    │
│     Stored in student_daily_progress                  │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite + Tailwind CSS + Framer Motion |
| Backend | Python FastAPI + Motor (async MongoDB) |
| Database | MongoDB (Atlas) |
| AI/LLM | Azure OpenAI (GPT-4) |
| Speech | Azure Cognitive Services (Speech-to-Text) |
| Storage | Azure Blob Storage (audio files) |
| Queue | Azure Queue Storage (async processing) |
| Auth | API Key + Tenant-based (MVP) |

---

## Key Design Decisions

1. **JSON over Markdown** — LLM returns structured JSON blocks, not free-form markdown. Frontend controls rendering. No broken diagrams, inconsistent tables, or formatting surprises.

2. **Block-based UI** — Each content type (concept, terms, steps, formula) has its own React component. Consistent, predictable, mobile-friendly.

3. **Grounded content** — LLM NEVER generates from its own knowledge. Always anchored to teacher transcript + NCERT textbook. No contradiction with what teacher taught.

4. **Independent learning modes** — Summary, Story, Flashcards, Try It, Quiz are all standalone. Student can access any mode without completing another first.

5. **Adaptive via checkpoint** — 3 quick questions after summary determine the recommended learning path. Same content, different depth and mode per student.

6. **Schema validation + fallback** — If LLM returns invalid JSON, system falls back to curriculum data. Never shows a broken page.

---

## What's Built (MVP Demo)

- [x] Block-based summary with 8 content types
- [x] Quick Check (3 checkpoint questions from same LLM call)
- [x] Adaptive path (score-based recommendations)
- [x] Standalone Flashcards + Mind Map tab
- [x] Standalone Try It Yourself tab (4 widget types)
- [x] Story generation with panels + end card
- [x] Daily Quiz with XP + streaks + leaderboard
- [x] AI Tutor chat (context-aware)
- [x] Demo mode flag for MVP presentations
- [x] Class-level language adaptation (3-5, 6-7, 8-9)

## What's Next (Post-MVP)

- [ ] Real teacher audio capture + transcription pipeline
- [ ] Textbook diagram images in curriculum dump
- [ ] Spaced repetition (resurface weak topics)
- [ ] Per-student quiz difficulty adaptation
- [ ] Parent dashboard
- [ ] Teacher analytics dashboard
