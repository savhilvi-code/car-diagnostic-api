from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Car Diagnostic API is working"}

@app.post("/search")
def search(query: dict):
    return {
        "results": [
            {
                "forum": "test_forum",
                "title": f"Example result for {query.get('query')}",
                "url": "https://example.com",
                "post": "This is a test post",
                "comments": ["comment1", "comment2"]
            }
        ]
    }
