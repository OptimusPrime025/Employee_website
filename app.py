from flask import Flask, render_template, request, redirect, jsonify
import psycopg2
from psycopg2 import sql
import os


app = Flask(__name__)

# --------------------------------------------------------
# SHARED DB CONNECTION
# --------------------------------------------------------
def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    return conn

# --------------------------------------------------------
# ADDED FROM tables.py
# --------------------------------------------------------
def create_dynamic_table(organization, roles):
    conn = get_db_connection()
    cur = conn.cursor()

    table_name = f"{organization.lower()}_employees"

    # 1) Drop table if it already exists
    drop_query = sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name))
    cur.execute(drop_query)

    # Prepare the default columns
    default_columns = [
        ("Employee_ID", "VARCHAR(50) PRIMARY KEY"),
        ("Employee_name", "VARCHAR(100)"),
        ("Designation", "VARCHAR(100)"),
        ("Role", "VARCHAR(100)")
    ]

    # Create columns for each role
    dynamic_columns = [(role.replace(' ', '_'), "INT") for role in roles]

    # 2) Create a new table with the default and dynamic columns
    create_query = sql.SQL("CREATE TABLE {} ({})").format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(col), sql.SQL(dtype))
            for col, dtype in default_columns + dynamic_columns
        )
    )

    cur.execute(create_query)
    conn.commit()
    cur.close()
    conn.close()

@app.route('/create_roles_table', methods=['POST'])
def create_roles_table():
    data = request.json
    roles = data.get('roles', [])
    organization = data.get('organization', 'default_org')

    if not roles:
        return jsonify({"message": "No roles provided."}), 400

    try:
        create_dynamic_table(organization, roles)
        return jsonify({
            "message": f"Table '{organization.lower()}_employees' created successfully with columns: {', '.join(roles)}"
        }), 200
    except Exception as e:
        return jsonify({"message": f"Error creating table: {str(e)}"}), 500

# --------------------------------------------------------
# ORIGINAL app.py CODE
# --------------------------------------------------------
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/add_employee')
def add_employee():
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch dynamic role columns from school_employees
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns
        WHERE table_name='school_employees' 
          AND ordinal_position > 4
        ORDER BY ordinal_position
    """)
    roles = [col[0] for col in cur.fetchall()]

    # Fetch all employees, sorted numerically by Employee_ID
    cur.execute('SELECT * FROM school_employees ORDER BY CAST("Employee_ID" AS int) ASC')
    employees = cur.fetchall()

    # Fetch all column names for display
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns
        WHERE table_name='school_employees'
        ORDER BY ordinal_position
    """)
    columns = [col[0] for col in cur.fetchall()]

    cur.close()
    conn.close()

    return render_template('add_employee.html', roles=roles, employees=employees, columns=columns)

@app.route('/submit_employee', methods=['POST'])
def submit_employee():
    """
    Insert a new employee row into school_employees.
    The Employee_ID column is a VARCHAR, so we must cast it to int
    when finding the max, then convert the new ID back to string.
    """
    data = request.form
    employee_name = data['Employee_name']
    designation = data['Designation']
    role_selected = data['Role']

    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch dynamic columns
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns
        WHERE table_name='school_employees'
          AND ordinal_position > 4
        ORDER BY ordinal_position
    """)
    columns = [col[0] for col in cur.fetchall()]

    # Generate new Employee_ID by casting existing IDs to int
    cur.execute('SELECT MAX(CAST("Employee_ID" as int)) FROM school_employees')
    last_id = cur.fetchone()[0]
    if last_id is None:
        last_id = 0
    new_id_int = last_id + 1
    new_id_str = str(new_id_int)  # store as string in DB

    # Prepare columns & values
    insert_columns = ['Employee_ID', 'Employee_name', 'Designation', 'Role'] + columns
    insert_values = [new_id_str, employee_name, designation, role_selected]

    # Append skill ratings
    for col in columns:
        insert_values.append(int(data.get(col, 0)))

    # Insert into school_employees
    query = sql.SQL('INSERT INTO school_employees ({}) VALUES ({})').format(
        sql.SQL(', ').join(map(sql.Identifier, insert_columns)),
        sql.SQL(', ').join(sql.Placeholder() * len(insert_values))
    )
    cur.execute(query, insert_values)

    conn.commit()
    cur.close()
    conn.close()

    return redirect('/add_employee')

# JSON endpoint to get existing data for a specific employee
@app.route('/employee_data/<int:emp_id>', methods=['GET'])
def get_employee_data(emp_id):
    """
    Because Employee_ID is stored as VARCHAR,
    we must convert the incoming integer to a string before querying.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    emp_id_str = str(emp_id)
    cur.execute('SELECT * FROM school_employees WHERE "Employee_ID" = %s', (emp_id_str,))
    row = cur.fetchone()

    # Get column names
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns
        WHERE table_name='school_employees'
        ORDER BY ordinal_position
    """)
    columns = [col[0] for col in cur.fetchall()]

    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Employee not found"}), 404

    # Convert to dict
    data = dict(zip(columns, row))
    return jsonify(data), 200

# Update skill ratings for a specific employee
@app.route('/update_employee', methods=['POST'])
def update_employee():
    data = request.json
    employee_id = data.get('Employee_ID')
    updated_ratings = data.get('ratings', {})

    if not employee_id:
        return jsonify({"error": "Employee_ID is required"}), 400
    if not updated_ratings:
        return jsonify({"error": "No ratings provided"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    set_clauses = []
    values = []
    for role, rating in updated_ratings.items():
        set_clauses.append(sql.SQL('{} = %s').format(sql.Identifier(role)))
        values.append(rating)

    update_query = (
        sql.SQL('UPDATE school_employees SET ') +
        sql.SQL(', ').join(set_clauses) +
        sql.SQL(' WHERE "Employee_ID" = %s')
    )
    values.append(employee_id)
    cur.execute(update_query, values)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Employee skill ratings updated successfully"}), 200

# --------------------------------------------------------
# CANDIDATE CREDENTIALS
# --------------------------------------------------------
@app.route('/select_candidates')
def select_candidates():
    """
    Show a page with all employees from school_employees
    plus fields to update Email & Phone in candidate_credentials
    and display the updated candidate_credentials below.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Ensure new table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidate_credentials (
            employee_id INT PRIMARY KEY,
            employee_name VARCHAR(100),
            email VARCHAR(100),
            phone VARCHAR(20)
        );
    """)

    # Fetch employees, sorted numerically by Employee_ID
    cur.execute('SELECT "Employee_ID", "Employee_name" FROM school_employees ORDER BY CAST("Employee_ID" as int) ASC')
    employees = cur.fetchall()

    # Fetch existing candidate credentials
    cur.execute("SELECT employee_id, employee_name, email, phone FROM candidate_credentials ORDER BY employee_id ASC")
    cred_rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'select_candidates.html',
        employees=employees,
        cred_rows=cred_rows
    )

@app.route('/update_candidate', methods=['POST'])
def update_candidate():
    """
    Insert or update candidate's email/phone in candidate_credentials,
    then redirect back to /select_candidates to show updated table.
    """
    employee_id = request.form.get('employee_id')
    employee_name = request.form.get('employee_name')
    email = request.form.get('email', '')
    phone = request.form.get('phone', '')

    if not employee_id or not employee_name:
        return "Missing employee info", 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Ensure table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidate_credentials (
            employee_id INT PRIMARY KEY,
            employee_name VARCHAR(100),
            email VARCHAR(100),
            phone VARCHAR(20)
        );
    """)

    # UPSERT logic
    upsert_query = """
    INSERT INTO candidate_credentials (employee_id, employee_name, email, phone)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (employee_id)
    DO UPDATE SET
      employee_name = EXCLUDED.employee_name,
      email = EXCLUDED.email,
      phone = EXCLUDED.phone
    """
    cur.execute(upsert_query, (employee_id, employee_name, email, phone))

    conn.commit()
    cur.close()
    conn.close()

    return redirect('/select_candidates')

# --------------------------------------------------------
# FILE UPLOAD
# --------------------------------------------------------
@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    # Check if the post request has the file part
    if 'pdfFile' not in request.files:
        return "No file part in the request", 400

    file = request.files['pdfFile']
    if file.filename == '':
        return "No selected file", 400

    # You can rename the file to "Document.pdf" and store in the specific path
    save_path = "C:/Users/sivad/Documents/Chatbot/RAG/Document.pdf"

    # Save the file
    file.save(save_path)

    return redirect('/')  # or return a message if you prefer

# --------------------------------------------------------
# LIMITS FEATURE
# --------------------------------------------------------
@app.route('/set_limits')
def set_limits():
    """
    1) Create a table named 'limits' if it doesn't exist:
       Columns: role (PK), min_hours, max_hours
    2) Upsert each distinct role from 'school_employees' into 'limits' if not present.
    3) **Remove** any leftover roles from 'limits' that are not currently used in 'school_employees'.
    4) Fetch & display the updated rows from 'limits'.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 1) Create the limits table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS limits (
            role VARCHAR(100) PRIMARY KEY,
            min_hours INT,
            max_hours INT
        );
    """)

    # 2) Get distinct roles from school_employees
    cur.execute('SELECT DISTINCT "Role" FROM school_employees')
    distinct_roles = [row[0] for row in cur.fetchall()]

    # Insert any new roles into limits (default min/max = 0)
    for r in distinct_roles:
        cur.execute("""
            INSERT INTO limits (role, min_hours, max_hours)
            VALUES (%s, 0, 0)
            ON CONFLICT (role) DO NOTHING
        """, (r,))

    # 3) Remove old roles from limits that are NOT in the current distinct_roles
    if distinct_roles:
        # Safely build a DELETE statement using placeholders
        placeholders = ', '.join(['%s'] * len(distinct_roles))
        delete_query = f"DELETE FROM limits WHERE role NOT IN ({placeholders})"
        cur.execute(delete_query, distinct_roles)
    else:
        # If no roles at all in school_employees, then remove everything
        cur.execute("DELETE FROM limits")

    conn.commit()

    # 4) Fetch all rows from limits (now pruned)
    cur.execute("SELECT role, min_hours, max_hours FROM limits ORDER BY role ASC")
    limit_rows = cur.fetchall()

    cur.close()
    conn.close()

    # Render the updated limits in the template
    return render_template('limits.html', limit_rows=limit_rows)

@app.route('/update_limits', methods=['POST'])
def update_limits():
    """
    Receives JSON with: { role, min_hours, max_hours }
    Updates the 'limits' table accordingly.
    Returns JSON {success: True} on success or {success: False, error: "..."} on failure.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    role = data.get('role')
    min_h = data.get('min_hours')
    max_h = data.get('max_hours')

    if not role:
        return jsonify({"success": False, "error": "Missing role"}), 400

    try:
        min_val = int(min_h)
        max_val = int(max_h)
    except ValueError:
        return jsonify({"success": False, "error": "Min/Max must be integers"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE limits
               SET min_hours = %s,
                   max_hours = %s
             WHERE role = %s
        """, (min_val, max_val, role))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 500

    cur.close()
    conn.close()
    return jsonify({"success": True}), 200

# --------------------------------------------------------
# PAY (PLACEHOLDER)
# --------------------------------------------------------
@app.route('/pay')
def pay():
    return render_template('pay.html')

# --------------------------------------------------------
# MAIN ENTRY
# --------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, port=5000)
