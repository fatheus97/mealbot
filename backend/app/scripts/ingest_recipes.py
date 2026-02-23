# scripts/ingest_recipes.py
import json
from pathlib import Path
from fastembed import TextEmbedding
from sqlmodel import Session

from app.db import engine
from app.models.db_models import RecipeRow

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "recipes.json"


def main():

    model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        recipes = json.load(f)

    with Session(engine) as session:
        for r in recipes:
            text_for_embedding = (
                f"Title: {r['title']}\n\n"
                f"Ingredients: {', '.join(r['ingredients'])}\n\n"
                f"Steps: {' '.join(r['steps'])}"
            )
            emb = list(model.embed([text_for_embedding]))[0]
            row = RecipeRow(
                title=r["title"],
                ingredients_text="; ".join(r["ingredients"]),
                steps_text="\n".join(r["steps"]),
                cuisine=r.get("cuisine"),
                tags_text="; ".join(r.get("tags", [])),
                embedding=emb.tolist(),
            )
            session.add(row)
        session.commit()


if __name__ == "__main__":
    main()
