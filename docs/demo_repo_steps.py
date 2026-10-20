"""Builds the gpa-calc sample repo one step at a time. step(n) writes files for step n."""
import os, sys, textwrap
from pathlib import Path

def w(path, s):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(textwrap.dedent(s).lstrip())

STEPS = {}
def step(f): STEPS[len(STEPS)+1] = f; return f

@step
def s1():
    w("gpa.py", '''
    GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}


    def gpa(courses):
        """courses: list of (grade, credits) tuples."""
        total = sum(GRADE_POINTS[g] * c for g, c in courses)
        credits = sum(c for _, c in courses)
        return total / credits
    ''')

@step
def s2():
    s = Path("gpa.py").read_text()
    s = s.replace("        credits = sum(c for _, c in courses)\n        return total / credits",
                  "        credits = sum(c for _, c in courses)\n        if credits == 0:\n            return 0.0\n        return round(total / credits, 2)")
    s = s.replace("    credits = sum(c for _, c in courses)\n    return total / credits",
                  "    credits = sum(c for _, c in courses)\n    if credits == 0:\n        return 0.0\n    return round(total / credits, 2)")
    Path("gpa.py").write_text(s)

@step
def s3():
    w("cli.py", '''
    import argparse
    import csv

    from gpa import gpa


    def read_courses(path):
        with open(path, newline="") as fh:
            return [(row["grade"].strip().upper(), float(row["credits"])) for row in csv.DictReader(fh)]


    def main():
        parser = argparse.ArgumentParser(description="Compute GPA from a CSV of courses")
        parser.add_argument("csv_file", help="CSV with columns: course,grade,credits")
        args = parser.parse_args()
        print(f"GPA: {gpa(read_courses(args.csv_file)):.2f}")


    if __name__ == "__main__":
        main()
    ''')
    w("sample.csv", '''
    course,grade,credits
    Data Structures,A,4
    Linear Algebra,B,3
    Computer Networks,A,3
    Physical Education,C,1
    ''')

@step
def s4():
    w("tests/test_gpa.py", '''
    from gpa import gpa


    def test_simple_average():
        assert gpa([("A", 3), ("B", 3)]) == 3.5


    def test_empty_list_returns_zero():
        assert gpa([]) == 0.0


    def test_weighted_by_credits():
        assert gpa([("A", 4), ("C", 1)]) == 3.6
    ''')

@step
def s5():
    w("README.md", '''
    # gpa-calc

    Tiny GPA calculator for my course list.

    ## Usage

    ```bash
    python cli.py sample.csv
    ```

    The CSV needs `course`, `grade` and `credits` columns.
    ''')

@step
def s6():
    s = Path("gpa.py").read_text()
    s = s.replace('GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}',
    'GRADE_POINTS = {\n    "A": 4.0, "A-": 3.7,\n    "B+": 3.3, "B": 3.0, "B-": 2.7,\n    "C+": 2.3, "C": 2.0, "C-": 1.7,\n    "D": 1.0, "F": 0.0,\n}')
    Path("gpa.py").write_text(s)
    t = Path("tests/test_gpa.py").read_text()
    t += '\n\ndef test_plus_minus_grades():\n    assert gpa([("A-", 3), ("B+", 3)]) == 3.5\n'
    Path("tests/test_gpa.py").write_text(t)

# the change left staged for the live demo
@step
def s7():
    s = Path("gpa.py").read_text()
    s = s.replace('def gpa(courses):\n    """courses: list of (grade, credits) tuples."""\n',
    'class UnknownGradeError(ValueError):\n    pass\n\n\ndef gpa(courses):\n    """courses: list of (grade, credits) tuples."""\n    for grade, _ in courses:\n        if grade not in GRADE_POINTS:\n            raise UnknownGradeError(f"unknown grade {grade!r}, expected one of {sorted(GRADE_POINTS)}")\n')
    Path("gpa.py").write_text(s)
    c = Path("cli.py").read_text()
    c = c.replace("import csv\n", "import csv\nimport sys\n").replace("from gpa import gpa", "from gpa import UnknownGradeError, gpa")
    c = c.replace('        print(f"GPA: {gpa(read_courses(args.csv_file)):.2f}")',
    '        try:\n            print(f"GPA: {gpa(read_courses(args.csv_file)):.2f}")\n        except UnknownGradeError as exc:\n            sys.exit(f"error: {exc}")')
    c = c.replace('    print(f"GPA: {gpa(read_courses(args.csv_file)):.2f}")',
    '    try:\n        print(f"GPA: {gpa(read_courses(args.csv_file)):.2f}")\n    except UnknownGradeError as exc:\n        sys.exit(f"error: {exc}")')
    Path("cli.py").write_text(c)

if __name__ == "__main__":
    STEPS[int(sys.argv[1])]()
