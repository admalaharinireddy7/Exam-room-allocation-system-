
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import sqlite3
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "smart_exam_allocation_secret"
DATABASE = "exam_allocation.db"


# ---------------- DATABASE ----------------

def get_db():
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_no TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            year INTEGER NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            students TEXT NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_name TEXT NOT NULL UNIQUE,
            capacity INTEGER NOT NULL
        )
    """)

    room_columns = [
        row["name"]
        for row in con.execute("PRAGMA table_info(rooms)").fetchall()
    ]

    if "room_name" not in room_columns and "name" in room_columns:
        con.execute("ALTER TABLE rooms RENAME COLUMN name TO room_name")
    elif "room_name" not in room_columns:
        con.execute("ALTER TABLE rooms ADD COLUMN room_name TEXT")

    room_columns = [
        row["name"]
        for row in con.execute("PRAGMA table_info(rooms)").fetchall()
    ]

    if "capacity" not in room_columns:
        con.execute(
            "ALTER TABLE rooms ADD COLUMN capacity INTEGER DEFAULT 30"
        )

    con.execute("""
        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            slot INTEGER NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS seat_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_roll_no TEXT NOT NULL,
            room_id INTEGER NOT NULL,
            seat_number INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            UNIQUE(exam_id, student_roll_no),
            UNIQUE(exam_id, seat_number)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_roll_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Absent',
            UNIQUE(exam_id, student_roll_no)
        )
    """)

    con.commit()
    con.close()


def get_exam_time(slot):
    times = {
        1: "9:00 AM - 12:00 PM",
        2: "1:00 PM - 4:00 PM"
    }
    return times.get(slot, f"Slot {slot}")


# ---------------- HOME PAGE ----------------

@app.route("/")
def index():
    con = get_db()

    students = con.execute(
        "SELECT * FROM students ORDER BY roll_no"
    ).fetchall()

    exams = con.execute(
        "SELECT * FROM exams ORDER BY exam_date, id"
    ).fetchall()

    rooms = con.execute(
        "SELECT * FROM rooms ORDER BY room_name"
    ).fetchall()

    allocations = con.execute("""
        SELECT allocations.id, exams.id AS exam_id,
               exams.subject, exams.exam_date,
               allocations.slot, rooms.room_name, rooms.capacity
        FROM allocations
        JOIN exams ON allocations.exam_id = exams.id
        JOIN rooms ON allocations.room_id = rooms.id
        ORDER BY exams.exam_date, allocations.slot
    """).fetchall()

    seating = con.execute("""
        SELECT exams.subject, exams.exam_date,
               seat_allocations.student_roll_no,
               students.name, students.department,
               seat_allocations.seat_number,
               rooms.room_name, rooms.capacity, seat_allocations.slot
        FROM seat_allocations
        JOIN exams ON seat_allocations.exam_id = exams.id
        JOIN students ON seat_allocations.student_roll_no = students.roll_no
        JOIN rooms ON seat_allocations.room_id = rooms.id
        ORDER BY exams.exam_date, seat_allocations.slot,
                 rooms.room_name, seat_allocations.seat_number
    """).fetchall()

    con.close()

    return render_template(
        "index.html",
        students=students,
        exams=exams,
        rooms=rooms,
        allocations=allocations,
        seating=seating,
        get_exam_time=get_exam_time
    )


# ---------------- ADD STUDENT ----------------

@app.route("/add_student", methods=["POST"])
def add_student():
    name = request.form.get("name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    department = request.form.get("department", "").strip()
    year = request.form.get("year", "").strip()

    if not all([name, roll_no, department, year]):
        flash("Please fill in all student details.", "warning")
        return redirect(url_for("index"))

    try:
        year = int(year)
        if year < 1:
            raise ValueError

        con = get_db()
        con.execute("""
            INSERT INTO students (name, roll_no, department, year)
            VALUES (?, ?, ?, ?)
        """, (name, roll_no, department, year))
        con.commit()
        con.close()
        flash("Student added successfully!", "success")

    except sqlite3.IntegrityError:
        flash("This roll number already exists.", "danger")
    except ValueError:
        flash("Enter a valid year.", "danger")

    return redirect(url_for("index"))


# ---------------- ADD EXAM ----------------

@app.route("/add_exam", methods=["POST"])
def add_exam():
    subject = request.form.get("subject", "").strip()
    exam_date = request.form.get("exam_date", "").strip()
    students_text = request.form.get("students", "").strip()

    if not all([subject, exam_date, students_text]):
        flash("Please fill in all exam details.", "warning")
        return redirect(url_for("index"))

    rolls = list(dict.fromkeys(
        r.strip() for r in students_text.split(",") if r.strip()
    ))

    if not rolls:
        flash("Enter at least one student roll number.", "warning")
        return redirect(url_for("index"))

    con = get_db()
    placeholders = ",".join("?" for _ in rolls)

    registered = con.execute(
        f"SELECT roll_no FROM students WHERE roll_no IN ({placeholders})",
        rolls
    ).fetchall()

    registered_rolls = {r["roll_no"] for r in registered}
    missing = [r for r in rolls if r not in registered_rolls]

    if missing:
        con.close()
        flash("Unregistered roll numbers: " + ", ".join(missing), "danger")
        return redirect(url_for("index"))

    con.execute("""
        INSERT INTO exams (subject, exam_date, students)
        VALUES (?, ?, ?)
    """, (subject, exam_date, ",".join(rolls)))

    con.commit()
    con.close()

    flash("Exam added successfully!", "success")
    return redirect(url_for("index"))


# ---------------- DELETE EXAM ----------------

@app.route("/delete_exam/<int:exam_id>", methods=["POST"])
def delete_exam(exam_id):
    con = get_db()
    con.execute("DELETE FROM attendance WHERE exam_id = ?", (exam_id,))
    con.execute("DELETE FROM seat_allocations WHERE exam_id = ?", (exam_id,))
    con.execute("DELETE FROM allocations WHERE exam_id = ?", (exam_id,))
    con.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    con.commit()
    con.close()

    flash("Exam deleted successfully.", "success")
    return redirect(url_for("index"))


# ---------------- ADD ROOM ----------------

@app.route("/add_room", methods=["POST"])
def add_room():
    room_name = request.form.get("room_name", "").strip()
    capacity = request.form.get("capacity", "").strip()

    if not room_name or not capacity:
        flash("Enter the room name and capacity.", "warning")
        return redirect(url_for("index"))

    try:
        capacity = int(capacity)
        if capacity < 1:
            raise ValueError

        con = get_db()
        con.execute("""
            INSERT INTO rooms (room_name, capacity)
            VALUES (?, ?)
        """, (room_name, capacity))
        con.commit()
        con.close()
        flash("Room added successfully!", "success")

    except sqlite3.IntegrityError:
        flash("This room name already exists.", "danger")
    except ValueError:
        flash("Capacity must be a positive number.", "danger")

    return redirect(url_for("index"))


# ---------------- GENERATE TIMETABLE AND SEATS ----------------

@app.route("/generate", methods=["POST"])
def generate():
    con = get_db()

    exams = con.execute(
        "SELECT * FROM exams ORDER BY exam_date, id"
    ).fetchall()

    rooms = con.execute(
        "SELECT * FROM rooms ORDER BY capacity, room_name"
    ).fetchall()

    if not exams:
        con.close()
        flash("Please add exams first.", "warning")
        return redirect(url_for("index"))

    if not rooms:
        con.close()
        flash("Please add rooms first.", "warning")
        return redirect(url_for("index"))

    exam_students = {}

    for exam in exams:
        rolls = list(dict.fromkeys(
            r.strip() for r in exam["students"].split(",") if r.strip()
        ))

        if not rolls:
            con.close()
            flash(f"No students listed for {exam['subject']}.", "danger")
            return redirect(url_for("index"))

        placeholders = ",".join("?" for _ in rolls)
        registered = con.execute(
            f"SELECT roll_no FROM students WHERE roll_no IN ({placeholders})",
            rolls
        ).fetchall()

        registered_rolls = {r["roll_no"] for r in registered}

        if any(r not in registered_rolls for r in rolls):
            con.close()
            flash(f"Check student roll numbers for {exam['subject']}.", "danger")
            return redirect(url_for("index"))

        if not any(room["capacity"] >= len(rolls) for room in rooms):
            con.close()
            flash(f"No room has enough capacity for {exam['subject']}.", "danger")
            return redirect(url_for("index"))

        exam_students[exam["id"]] = rolls

    con.execute("DELETE FROM seat_allocations")
    con.execute("DELETE FROM allocations")

    student_slots = set()
    room_slots = set()

    for exam in exams:
        exam_id = exam["id"]
        exam_date = exam["exam_date"]
        rolls = exam_students[exam_id]

        slot = 1
        while any(
            (exam_date, roll, slot) in student_slots
            for roll in rolls
        ):
            slot += 1

        selected_room = None

        for room in rooms:
            if room["capacity"] < len(rolls):
                continue

            room_key = (room["id"], exam_date, slot)
            if room_key not in room_slots:
                selected_room = room
                break

        if selected_room is None:
            con.rollback()
            con.close()
            flash(
                f"No available room for {exam['subject']} on {exam_date}. "
                "Add another suitable room.",
                "danger"
            )
            return redirect(url_for("index"))

        room_id = selected_room["id"]

        con.execute("""
            INSERT INTO allocations (exam_id, room_id, slot)
            VALUES (?, ?, ?)
        """, (exam_id, room_id, slot))

        for seat_no, roll in enumerate(rolls, start=1):
            con.execute("""
                INSERT INTO seat_allocations
                    (exam_id, student_roll_no, room_id, seat_number, slot)
                VALUES (?, ?, ?, ?, ?)
            """, (exam_id, roll, room_id, seat_no, slot))

            student_slots.add((exam_date, roll, slot))

        room_slots.add((room_id, exam_date, slot))

    con.commit()
    con.close()

    flash("Timetable and seating arrangement generated successfully!", "success")
    return redirect(url_for("index"))


# ---------------- STUDENT SEARCH ----------------

@app.route("/student_search", methods=["GET", "POST"])
def student_search():
    student = None
    results = []
    searched = False

    if request.method == "POST":
        roll_no = request.form.get("roll_no", "").strip()
        searched = True
        con = get_db()

        student = con.execute(
            "SELECT * FROM students WHERE roll_no = ?", (roll_no,)
        ).fetchone()

        if student:
            results = con.execute("""
                SELECT exams.subject, exams.exam_date,
                       allocations.slot, rooms.room_name,
                       seat_allocations.seat_number,
                       attendance.status AS attendance_status
                FROM exams
                LEFT JOIN allocations ON exams.id = allocations.exam_id
                LEFT JOIN rooms ON allocations.room_id = rooms.id
                LEFT JOIN seat_allocations
                    ON exams.id = seat_allocations.exam_id
                    AND seat_allocations.student_roll_no = ?
                LEFT JOIN attendance
                    ON exams.id = attendance.exam_id
                    AND attendance.student_roll_no = ?
                WHERE ',' || exams.students || ',' LIKE ?
                ORDER BY exams.exam_date
            """, (
                roll_no, roll_no, "%," + roll_no + ",%"
            )).fetchall()

        con.close()

    return render_template(
        "student_search.html",
        student=student,
        results=results,
        searched=searched,
        get_exam_time=get_exam_time
    )


# ---------------- TIMETABLE PDF ----------------

@app.route("/download_pdf")
def download_pdf():
    con = get_db()

    rows = con.execute("""
        SELECT exams.subject, exams.exam_date, allocations.slot,
               rooms.room_name, rooms.capacity
        FROM allocations
        JOIN exams ON allocations.exam_id = exams.id
        JOIN rooms ON allocations.room_id = rooms.id
        ORDER BY exams.exam_date, allocations.slot
    """).fetchall()

    con.close()

    if not rows:
        flash("Generate the timetable before downloading the PDF.", "warning")
        return redirect(url_for("index"))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("Smart Exam Allocation System", styles["Title"]),
        Spacer(1, 12),
        Paragraph("Examination Timetable", styles["Heading2"]),
        Spacer(1, 12)
    ]

    data = [["Subject", "Exam Date", "Exam Time", "Room", "Capacity"]]

    for row in rows:
        data.append([
            row["subject"], row["exam_date"],
            get_exam_time(row["slot"]),
            row["room_name"], str(row["capacity"])
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#edf2f8")])
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Exam_Timetable.pdf",
        mimetype="application/pdf"
    )


# ---------------- SEATING PDF ----------------

@app.route("/download_seating_pdf")
def download_seating_pdf():
    con = get_db()

    rows = con.execute("""
        SELECT exams.subject, exams.exam_date, seat_allocations.slot,
               students.name, students.department,
               seat_allocations.student_roll_no,
               rooms.room_name, seat_allocations.seat_number
        FROM seat_allocations
        JOIN exams ON seat_allocations.exam_id = exams.id
        JOIN students ON seat_allocations.student_roll_no = students.roll_no
        JOIN rooms ON seat_allocations.room_id = rooms.id
        ORDER BY exams.exam_date, seat_allocations.slot,
                 rooms.room_name, seat_allocations.seat_number
    """).fetchall()

    con.close()

    if not rows:
        flash("Generate the seating arrangement first.", "warning")
        return redirect(url_for("index"))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("Smart Exam Allocation System", styles["Title"]),
        Spacer(1, 10),
        Paragraph("Student-wise Seating Arrangement", styles["Heading2"]),
        Spacer(1, 12)
    ]

    data = [[
        "Subject", "Exam Date", "Time", "Student Name",
        "Roll Number", "Department", "Room", "Seat No."
    ]]

    for row in rows:
        data.append([
            row["subject"], row["exam_date"],
            get_exam_time(row["slot"]), row["name"],
            row["student_roll_no"], row["department"],
            row["room_name"], str(row["seat_number"])
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#edf2f8")])
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Student_Seating_Arrangement.pdf",
        mimetype="application/pdf"
    )


# ---------------- ATTENDANCE ----------------

@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    con = get_db()

    exams = con.execute("""
        SELECT id, subject, exam_date, students
        FROM exams ORDER BY exam_date, subject
    """).fetchall()

    selected_exam_id = request.values.get("exam_id", "").strip()
    selected_exam = None
    students_list = []

    if selected_exam_id:
        selected_exam = con.execute("""
            SELECT e.id, e.subject, e.exam_date, e.students,
                   r.room_name, a.slot
            FROM exams e
            LEFT JOIN allocations a ON a.exam_id = e.id
            LEFT JOIN rooms r ON r.id = a.room_id
            WHERE e.id = ?
        """, (selected_exam_id,)).fetchone()

        if selected_exam:
            rolls = [
                roll.strip()
                for roll in selected_exam["students"].split(",")
                if roll.strip()
            ]

            for roll in rolls:
                student = con.execute("""
                    SELECT name, roll_no, department
                    FROM students WHERE roll_no = ?
                """, (roll,)).fetchone()

                if student:
                    saved = con.execute("""
                        SELECT status FROM attendance
                        WHERE exam_id = ? AND student_roll_no = ?
                    """, (selected_exam_id, roll)).fetchone()

                    students_list.append({
                        "name": student["name"],
                        "roll_no": student["roll_no"],
                        "department": student["department"],
                        "status": saved["status"] if saved else "Absent"
                    })

    if request.method == "POST" and selected_exam:
        for student in students_list:
            roll = student["roll_no"]
            status = request.form.get("status_" + roll, "Absent")

            if status not in ("Present", "Absent"):
                status = "Absent"

            con.execute("""
                INSERT INTO attendance (exam_id, student_roll_no, status)
                VALUES (?, ?, ?)
                ON CONFLICT(exam_id, student_roll_no)
                DO UPDATE SET status = excluded.status
            """, (selected_exam_id, roll, status))

        con.commit()
        con.close()
        flash("Attendance saved successfully!", "success")
        return redirect(url_for("attendance", exam_id=selected_exam_id))

    con.close()

    return render_template(
        "attendance.html",
        exams=exams,
        selected_exam=selected_exam,
        students_list=students_list,
        selected_exam_id=selected_exam_id,
        get_exam_time=get_exam_time
    )


# ---------------- ATTENDANCE PDF ----------------

@app.route("/download_attendance_pdf")
def download_attendance_pdf():
    exam_id = request.args.get("exam_id", "").strip()

    if not exam_id:
        flash("Please select an exam first.", "warning")
        return redirect(url_for("attendance"))

    con = get_db()

    exam = con.execute("""
        SELECT e.subject, e.exam_date, r.room_name, a.slot
        FROM exams e
        LEFT JOIN allocations a ON a.exam_id = e.id
        LEFT JOIN rooms r ON r.id = a.room_id
        WHERE e.id = ?
    """, (exam_id,)).fetchone()

    if not exam:
        con.close()
        flash("Exam not found.", "danger")
        return redirect(url_for("attendance"))

    rows = con.execute("""
        SELECT s.name, s.roll_no, s.department, at.status
        FROM attendance at
        JOIN students s ON s.roll_no = at.student_roll_no
        WHERE at.exam_id = ?
        ORDER BY s.roll_no
    """, (exam_id,)).fetchall()

    con.close()

    if not rows:
        flash("Save attendance before downloading the PDF.", "warning")
        return redirect(url_for("attendance", exam_id=exam_id))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    room_name = exam["room_name"] or "Not allocated"
    exam_time = (
        get_exam_time(exam["slot"])
        if exam["slot"] is not None else "Not allocated"
    )

    elements = [
        Paragraph("Smart Exam Allocation System", styles["Title"]),
        Spacer(1, 10),
        Paragraph("Exam Hall Attendance Report", styles["Heading2"]),
        Spacer(1, 8),
        Paragraph(f"Subject: {exam['subject']}", styles["Normal"]),
        Paragraph(f"Exam Date: {exam['exam_date']}", styles["Normal"]),
        Paragraph(f"Room: {room_name}", styles["Normal"]),
        Paragraph(f"Exam Time: {exam_time}", styles["Normal"]),
        Spacer(1, 12)
    ]

    data = [[
        "S.No.", "Student Name", "Roll Number", "Department", "Attendance"
    ]]

    present_count = 0
    absent_count = 0

    for number, row in enumerate(rows, start=1):
        data.append([
            str(number), row["name"], row["roll_no"],
            row["department"], row["status"]
        ])

        if row["status"] == "Present":
            present_count += 1
        else:
            absent_count += 1

    data.append(["", "", "", "Present Count", str(present_count)])
    data.append(["", "", "", "Absent Count", str(absent_count)])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 7)
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Exam_Attendance.pdf",
        mimetype="application/pdf"
    )


# ---------------- ATTENDANCE DASHBOARD ----------------

@app.route("/attendance_dashboard")
def attendance_dashboard():
    con = get_db()

    totals = con.execute("""
        SELECT COUNT(*) AS total_marked,
               SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END)
                   AS present_count,
               SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END)
                   AS absent_count
        FROM attendance
    """).fetchone()

    total_marked = totals["total_marked"] or 0
    present_count = totals["present_count"] or 0
    absent_count = totals["absent_count"] or 0

    percentage = (
        round(present_count / total_marked * 100, 2)
        if total_marked else 0
    )

    subject_stats = con.execute("""
        SELECT exams.subject, exams.exam_date,
               COUNT(attendance.id) AS total_marked,
               SUM(CASE WHEN attendance.status = 'Present'
                   THEN 1 ELSE 0 END) AS present_count,
               SUM(CASE WHEN attendance.status = 'Absent'
                   THEN 1 ELSE 0 END) AS absent_count
        FROM exams
        LEFT JOIN attendance ON exams.id = attendance.exam_id
        GROUP BY exams.id
        ORDER BY exams.exam_date, exams.subject
    """).fetchall()

    con.close()

    return render_template(
        "attendance_dashboard.html",
        total_marked=total_marked,
        present_count=present_count,
        absent_count=absent_count,
        percentage=percentage,
        subject_stats=subject_stats
    )


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)







