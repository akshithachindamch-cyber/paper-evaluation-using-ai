from flask import Flask, render_template, request, redirect, session
import os
from pdf2image import convert_from_bytes
from PIL import Image
import io

from db import get_connection
from utils.ocr import extract_text
from utils.similarity import semantic_similarity
from utils.keyword_extractor import extract_keywords
from utils.scoring import calculate_score

app = Flask(__name__)
app.secret_key = "ai-paper-eval-secret"

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def highlight_keywords(text, keywords):
    for kw in keywords.split(","):
        if kw.strip():
            text = text.replace(kw, f"<mark>{kw}</mark>")
    return text

app.jinja_env.filters["highlight"] = highlight_keywords


def save_as_png(uploaded_file, output_path: str):
    """
    Save uploaded file as PNG.
      - If it's JPG/PNG → save directly
      - If it's PDF → convert first page to PNG
    Raises ValueError on failure or unsupported format.
    """
    if not uploaded_file or not uploaded_file.filename:
        raise ValueError("No file provided")

    filename = uploaded_file.filename.lower()

    # Supported image formats - save directly
    if filename.endswith(('.png', '.jpg', '.jpeg')):
        uploaded_file.save(output_path)
        return

    # PDF handling
    if filename.endswith('.pdf'):
        try:
            pdf_bytes = uploaded_file.read()
            images = convert_from_bytes(
                pdf_bytes,
                first_page=1,
                last_page=1,        # only first page
                dpi=180,            # reasonable quality / size balance
                fmt="png"
            )
            if not images:
                raise ValueError("No pages found in PDF")

            images[0].save(output_path, "PNG")
            return
        except Exception as e:
            raise ValueError(f"Failed to convert PDF to image: {str(e)}")

    raise ValueError("Unsupported file format. Allowed: JPG, JPEG, PNG, PDF")


# ---------------- HOME ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        mode = request.form.get("mode")

        if mode == "single":
            total_raw = request.form.get("total_questions", "").strip()
            if not total_raw.isdigit():
                return "Total questions is required for single mode", 400

            total = int(total_raw)
            roll_no = request.form.get("roll_no", "").strip()

            if not roll_no:
                return "Roll number is required", 400

            db = get_connection()
            cur = db.cursor()
            cur.execute(
                "INSERT INTO evaluation_sessions (student_roll) VALUES (%s)",
                (roll_no,)
            )
            session_id = cur.lastrowid
            db.commit()
            cur.close()
            db.close()

            session["session_id"] = session_id
            session["roll_no"] = roll_no
            session["mode"] = "single"

            return render_template("upload_question.html", qno=1, total=total)

        elif mode == "bulk":
            roll_nos = [
                r.strip() for r in request.form.get("roll_nos", "").split(",")
                if r.strip()
            ]

            if not roll_nos:
                return "No roll numbers provided", 400

            session["mode"] = "bulk"
            session["roll_nos"] = roll_nos
            session["bulk_session_ids"] = []

            db = get_connection()
            cur = db.cursor()
            for roll in roll_nos:
                cur.execute(
                    "INSERT INTO evaluation_sessions (student_roll) VALUES (%s)",
                    (roll,)
                )
                session["bulk_session_ids"].append(cur.lastrowid)
            db.commit()
            cur.close()
            db.close()

            return render_template(
                "upload_bulk.html",
                total_students=len(roll_nos),
                roll_nos=roll_nos
            )

        else:
            return "Invalid mode selected", 400

    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/features")
def features():
    return render_template("features.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------------- SINGLE UPLOAD ----------------
@app.route("/upload/<int:qno>/<int:total>", methods=["POST"])
def upload(qno, total):
    session_id = session.get("session_id")
    if not session_id:
        return "Session error", 400

    question = request.form["question"]
    faculty_keywords = [k.strip() for k in request.form["keywords"].split(",") if k.strip()]
    max_marks = int(request.form["marks"])

    model_file = request.files.get("model_answer")
    student_file = request.files.get("student_answer")

    if not model_file or not student_file:
        return "Missing required files", 400

    model_path = f"{UPLOAD_DIR}/model_{session_id}_{qno}.png"
    student_path = f"{UPLOAD_DIR}/student_{session_id}_{qno}.png"

    try:
        save_as_png(model_file, model_path)
        save_as_png(student_file, student_path)
    except ValueError as e:
        return f"File error: {str(e)}", 400

    model_text = extract_text(model_file)
    
    student_text = extract_text(student_file)
    
    print("\n================ OCR DEBUG =================")
    print("MODEL ANSWER TEXT:")
    print("------------------------------------------")
    print(model_text)
    print("------------------------------------------\n")

    print("STUDENT ANSWER TEXT:")
    print("------------------------------------------")
    print(student_text)
    print("------------------------------------------")
    print("============================================\n")


    similarity = semantic_similarity(model_text, student_text)
    model_keywords = extract_keywords(model_text)

    score, merged_keywords, reason = calculate_score(
        similarity=similarity,
        faculty_keywords=faculty_keywords,
        model_keywords=model_keywords,
        student_text=student_text,
        max_marks=max_marks,
        question_text=question,
        model_answer_text=model_text
    )

    db = get_connection()
    cur = db.cursor()

    cur.execute(
        """INSERT INTO questions
        (question_no, question_text, keywords, max_marks, session_id)
        VALUES (%s, %s, %s, %s, %s)""",
        (qno, question, ",".join(merged_keywords), max_marks, session_id)
    )
    qid = cur.lastrowid

    cur.execute(
        """INSERT INTO answers
        (question_id, model_answer_text, student_answer_text,
         similarity_score, final_marks, student_image_path, session_id, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (qid, model_text, student_text, similarity, score, student_path, session_id, reason)
    )

    db.commit()
    cur.close()
    db.close()

    if qno < total:
        return render_template("upload_question.html", qno=qno+1, total=total)

    return redirect("/result")


@app.route("/upload_bulk", methods=["POST"])
def upload_bulk():
    session_ids = session.get("bulk_session_ids")
    roll_nos = session.get("roll_nos")
    if not session_ids or not roll_nos:
        return "Session error", 400

    question = request.form["question"]
    faculty_keywords = [k.strip() for k in request.form["keywords"].split(",") if k.strip()]
    max_marks = int(request.form["marks"])

    model_file = request.files.get("model_answer")
    if not model_file or not model_file.filename:
        return "Model answer file is required", 400

    # Collect student files
    student_files = []
    for i in range(len(roll_nos)):
        file_key = f"student_answer_{i}"
        f = request.files.get(file_key)
        if not f or not f.filename:
            return f"Missing answer file for student {roll_nos[i]}", 400
        student_files.append(f)

    model_path = f"{UPLOAD_DIR}/model_bulk_{os.urandom(6).hex()}.png"

    try:
        save_as_png(model_file, model_path)
        model_text = extract_text(model_file)
        model_keywords = extract_keywords(model_text)

        db = get_connection()
        cur = db.cursor()

        # We'll store question IDs per session
        question_ids = {}

        for idx, (session_id, roll, student_file) in enumerate(zip(session_ids, roll_nos, student_files)):
            student_path = f"{UPLOAD_DIR}/student_{session_id}_q1.png"
            save_as_png(student_file, student_path)
            student_text = extract_text(student_file)

            similarity = semantic_similarity(model_text, student_text)

            score, merged_keywords, reason = calculate_score(
                similarity=similarity,
                faculty_keywords=faculty_keywords,
                model_keywords=model_keywords,
                student_text=student_text,
                max_marks=max_marks,
                question_text=question,
                model_answer_text=model_text
            )

            # Insert question for THIS session (every student gets their own question record)
            cur.execute(
                """INSERT INTO questions
                (question_no, question_text, keywords, max_marks, session_id)
                VALUES (%s, %s, %s, %s, %s)""",
                (1, question, ",".join(merged_keywords), max_marks, session_id)
            )
            qid = cur.lastrowid
            question_ids[session_id] = qid

            # Insert answer using THIS session's question_id
            cur.execute(
                """INSERT INTO answers
                (question_id, model_answer_text, student_answer_text,
                 similarity_score, final_marks, student_image_path, session_id, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (qid, model_text, student_text, similarity, score, student_path, session_id, reason)
            )

        db.commit()

    except ValueError as e:
        return f"File error: {str(e)}", 400
    except Exception as e:
        return f"Processing error: {str(e)}", 500
    finally:
        if 'cur' in locals():
            cur.close()
        if 'db' in locals():
            db.close()

    return redirect("/bulk_result")


# ---------------- BULK PREVIEW ----------------
@app.route("/bulk_preview", methods=["POST"])
def bulk_preview():
    roll_nos_str = request.form.get("roll_nos")
    roll_nos = [r.strip() for r in roll_nos_str.split(",") if r.strip()]
    
    if not roll_nos:
        return "No roll numbers provided", 400

    session["mode"] = "bulk"
    session["roll_nos"] = roll_nos
    session["bulk_session_ids"] = []

    db = get_connection()
    cur = db.cursor()
    for roll in roll_nos:
        cur.execute(
            "INSERT INTO evaluation_sessions (student_roll) VALUES (%s)",
            (roll,)
        )
        session["bulk_session_ids"].append(cur.lastrowid)
    db.commit()
    cur.close()
    db.close()

    return render_template("bulk_preview.html", roll_nos=roll_nos, total_students=len(roll_nos))


# ---------------- SINGLE RESULT ----------------
@app.route("/result")
def result():
    session_id = session.get("session_id")

    db = get_connection()
    cur = db.cursor(dictionary=True)

    cur.execute(
        """
        SELECT q.question_no AS qno, q.question_text, q.max_marks, q.keywords,
               a.final_marks AS score, a.student_answer_text,
               a.model_answer_text, a.student_image_path,
               a.reason, a.id AS answer_id
        FROM questions q
        JOIN answers a ON q.id = a.question_id
        WHERE q.session_id = %s
        ORDER BY q.question_no
        """,
        (session_id,)
    )

    data = cur.fetchall()
    cur.close()
    db.close()

    total_obtained = sum(d["score"] for d in data)
    total_max = sum(d["max_marks"] for d in data)

    return render_template(
        "result.html",
        data=data,
        total_obtained=total_obtained,
        total_max=total_max,
        roll_no=session.get("roll_no")
    )


# ---------------- BULK RESULT ----------------
@app.route("/bulk_result")
def bulk_result():
    session_ids = session.get("bulk_session_ids")
    roll_nos = session.get("roll_nos")
    if not session_ids or not roll_nos:
        return "Session error", 400

    db = get_connection()
    cur = db.cursor(dictionary=True)

    all_data = []
    for session_id, roll in zip(session_ids, roll_nos):
        cur.execute(
            """
            SELECT q.question_no AS qno, q.question_text, q.max_marks, q.keywords,
                   a.final_marks AS score, a.student_answer_text,
                   a.model_answer_text, a.student_image_path,
                   a.reason, a.id AS answer_id
            FROM questions q
            JOIN answers a ON q.id = a.question_id
            WHERE q.session_id = %s
            ORDER BY q.question_no
            """,
            (session_id,)
        )
        data = cur.fetchall()
        total_obtained = sum(d["score"] for d in data)
        total_max = sum(d["max_marks"] for d in data)
        all_data.append({
            "roll_no": roll,
            "data": data,
            "total_obtained": total_obtained,
            "total_max": total_max
        })

    cur.close()
    db.close()

    return render_template("bulk_result.html", all_data=all_data)


# ---------------- OVERRIDE ----------------
@app.route("/override", methods=["POST"])
def override():
    answer_id = request.form["answer_id"]
    new_marks = request.form["new_marks"]

    db = get_connection()
    cur = db.cursor()
    cur.execute(
        "UPDATE answers SET final_marks=%s WHERE id=%s",
        (new_marks, answer_id)
    )
    db.commit()
    cur.close()
    db.close()

    # 🔥 FIX: redirect based on evaluation mode
    mode = session.get("mode")

    if mode == "bulk":
        return redirect("/bulk_result")
    else:
        return redirect("/result")



# ---------------- DELETE SESSION ----------------
@app.route("/delete_session")
def delete_session():
    mode = session.get("mode")
    if mode == "bulk":
        session_ids = session.get("bulk_session_ids")
        db = get_connection()
        cur = db.cursor()
        for sid in session_ids:
            cur.execute("DELETE FROM evaluation_sessions WHERE id=%s", (sid,))
        db.commit()
        cur.close()
        db.close()
    else:
        session_id = session.get("session_id")

        db = get_connection()
        cur = db.cursor()
        cur.execute("DELETE FROM evaluation_sessions WHERE id=%s", (session_id,))
        db.commit()
        cur.close()
        db.close()

    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)