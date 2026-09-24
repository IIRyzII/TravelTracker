"""Run ORBIT locally:  python app.py  ->  http://127.0.0.1:5000

Production uses gunicorn with wsgi.py (see DEPLOY.md).
"""

import os

from orbit import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
