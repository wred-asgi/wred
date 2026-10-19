import orjson
from wred import App

app = App()


@app.route('/api/echo', methods=['POST'])
async def echo(request):
    try:
        data = await request.json()
    except orjson.JSONDecodeError:
        return {'error': 'Invalid JSON'}, 'application/json', 400
    if not isinstance(data, dict):
        return {'error': 'Send a JSON object'}, 'application/json', 400
    title = data.get('title')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        return {'error': 'Title must contain 1–100 characters'}, 'application/json', 400
    return {'title': title.strip()}
