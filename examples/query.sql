-- Press Run. Every statement below gets its own table of results.
--
-- The database is described in schema.sql, and rebuilt from it every single
-- time you press Run. So you cannot break it: change anything, delete
-- everything, press Run, and it is back the way it started.
--
-- Four tables: teachers, students, courses, enrollments.


-- Everything in a table. Start here when you do not know what is in one.
SELECT * FROM teachers;


-- Pick the rows you want with WHERE, and put them in order with ORDER BY.
SELECT title, period
FROM courses
WHERE period <= 3
ORDER BY period;


-- A JOIN follows the link between two tables. Every row in courses holds a
-- teacher_id, which is the id of a row in teachers, so this puts each course
-- next to the person who teaches it.
SELECT c.title, c.period, t.name AS teacher
FROM courses c
JOIN teachers t ON t.id = c.teacher_id
ORDER BY c.period;


-- ONE TEACHER, MANY COURSES. Franz appears twice above, because a JOIN gives
-- you one row per match, not one row per teacher. To get one row per teacher
-- you have to say so: GROUP BY collapses the matches and COUNT tells you how
-- many there were.
--
-- LEFT JOIN, not JOIN. A plain JOIN drops any teacher with no courses at all,
-- so the teacher you most want to find -- the one teaching nothing -- is the
-- one that silently disappears. Change it to JOIN and watch Petrov vanish.
SELECT t.name, COUNT(c.id) AS courses
FROM teachers t
LEFT JOIN courses c ON c.teacher_id = t.id
GROUP BY t.id
ORDER BY courses DESC, t.name;


-- Two joins, to cross a table that exists only to connect two others.
-- A student is in many courses and a course has many students, so neither
-- table can hold the link; enrollments does, one row at a time.
SELECT s.name, ROUND(AVG(e.grade), 1) AS average
FROM students s
JOIN enrollments e ON e.student_id = s.id
GROUP BY s.id
HAVING AVG(e.grade) >= 85
ORDER BY average DESC;


-- Your turn. Which course has the most students in it?
