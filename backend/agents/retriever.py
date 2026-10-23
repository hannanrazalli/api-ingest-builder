import re

from rank_bm25 import BM25Okapi

from backend.models.research import Chunk

QUERIES = [
    "authentication api key header",
    "endpoints parameters date range",
    "pagination rate limit",
]


class Retriever:
    async def run(self, ctx, documents, top_k=5):
        async with ctx.step("retriever", "Rank relevant documentation") as progress:
            chunks = []
            for document in documents:
                text = document.markdown
                for offset in range(0, len(text), 1050):
                    chunks.append(
                        Chunk(source_url=document.source_url, markdown=text[offset : offset + 1200])
                    )
            if not chunks:
                return []
            tokens = [re.findall(r"\w+", chunk.markdown.lower()) or ["empty"] for chunk in chunks]
            index = BM25Okapi(tokens)
            scores = sum(index.get_scores(re.findall(r"\w+", query)) for query in QUERIES)
            ranked = sorted(range(len(chunks)), key=lambda i: (-float(scores[i]), i))[:top_k]
            for i in ranked:
                chunks[i].score = float(scores[i])
            progress(f"Selected {len(ranked)} bounded chunks from {len(chunks)}")
            return [chunks[i] for i in ranked]
