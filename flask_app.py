import os.path

from flask import Flask, Response


app = Flask(__name__)

@app.route('/')
def root():
    return app.send_static_file('client.html')


if __name__ == "__main__":
    app.run()