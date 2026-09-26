-- The database, rebuilt from this file every time you press Run.
--
-- That means you can never wreck it: delete every row, drop every table,
-- press Run, and it is back. It also means anything you INSERT while
-- experimenting is gone on the next Run — if you want it to stay, add it
-- here.

DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS teachers;

-- Dropped in the reverse of the order they are created, because a table
-- cannot go while another table's REFERENCES still points at it.


CREATE TABLE teachers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    department TEXT NOT NULL
);

CREATE TABLE students (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    grade_level INTEGER NOT NULL
);

CREATE TABLE courses (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    period     INTEGER NOT NULL,
    teacher_id INTEGER REFERENCES teachers(id)
);

-- One row per student per course: this is how a many-to-many is stored,
-- because neither table can hold a list.
CREATE TABLE enrollments (
    student_id INTEGER NOT NULL REFERENCES students(id),
    course_id  INTEGER NOT NULL REFERENCES courses(id),
    grade      INTEGER,
    PRIMARY KEY (student_id, course_id)
);


INSERT INTO teachers (id, name, department) VALUES
    (1, 'Franz',    'Computer Science'),
    (2, 'Okonkwo',  'Computer Science'),
    (3, 'Alvarez',  'Mathematics'),
    (4, 'Bhatt',    'Mathematics'),
    (5, 'Nakamura', 'Science'),
    (6, 'Petrov',   'Science');
-- Petrov teaches nothing this semester. That is on purpose: it is the row
-- that shows you the difference between JOIN and LEFT JOIN.

INSERT INTO students (id, name, grade_level) VALUES
    (1,  'Ana',     11),
    (2,  'Ben',     12),
    (3,  'Carmen',  11),
    (4,  'Dev',     10),
    (5,  'Elena',   12),
    (6,  'Farid',   11),
    (7,  'Grace',   10),
    (8,  'Hana',    12),
    (9,  'Ivan',    11),
    (10, 'Jonas',   10);

INSERT INTO courses (id, title, period, teacher_id) VALUES
    (1, 'Intro to Programming', 2, 1),
    (2, 'Web Development',      4, 1),
    (3, 'Data Structures',      3, 2),
    (4, 'Algebra II',           1, 3),
    (5, 'Statistics',           5, 3),
    (6, 'Calculus',             2, 4),
    (7, 'Biology',              1, 5),
    (8, 'Chemistry',            6, 5);
-- Franz teaches two, Alvarez teaches two, Nakamura teaches two. That is the
-- one-to-many: one teacher, many courses.

INSERT INTO enrollments (student_id, course_id, grade) VALUES
    (1, 1, 94), (1, 4, 88), (1, 7, 91),
    (2, 2, 78), (2, 3, 85), (2, 6, 72),
    (3, 1, 88), (3, 5, 95), (3, 7, 83),
    (4, 1, 67), (4, 4, 74),
    (5, 2, 91), (5, 3, 89), (5, 6, 96), (5, 8, 90),
    (6, 1, 82), (6, 5, 79), (6, 8, 86),
    (7, 4, 93), (7, 7, 88),
    (8, 2, 85), (8, 6, 81), (8, 8, 77),
    (9, 1, 90), (9, 3, 76), (9, 5, 84),
    (10, 4, 65), (10, 7, 70);
-- Some grades are NULL-free on purpose and some students take more courses
-- than others, so COUNT and AVG give different answers per student rather
-- than the same one.
