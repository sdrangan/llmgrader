from graderchat.app import create_app
import os
questions_root = os.path.join(os.getcwd(), "questions")

app = create_app(questions_root=questions_root)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False) # use_reloader=False to avoid double loading during development
