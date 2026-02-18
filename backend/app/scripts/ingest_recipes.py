# scripts/ingest_recipes.py
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlmodel import Session

from app.db import engine, init_db
from app.models.db_models import RecipeRow

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "recipes.json"


def main():
    # ensure all tables, including RecipeRow, exist
    init_db()

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        recipes = json.load(f)

    with Session(engine) as session:
        for r in recipes:
            text_for_embedding = (
                f"Title: {r['title']}\n\n"
                f"Ingredients: {', '.join(r['ingredients'])}\n\n"
                f"Steps: {' '.join(r['steps'])}"
            )
            emb = model.encode(text_for_embedding, normalize_embeddings=True)
            row = RecipeRow(
                title=r["title"],
                ingredients_text="; ".join(r["ingredients"]),
                steps_text="\n".join(r["steps"]),
                cuisine=r.get("cuisine"),
                tags_text="; ".join(r.get("tags", [])),
                embedding=emb.tobytes(),
            )
            session.add(row)
        session.commit()


if __name__ == "__main__":
    main()
