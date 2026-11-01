<?php
// The page at /. include pastes another file in here, so every page shares
// one header and one footer: change includes/header.php and they all change.
session_start();

// A list to play with. It lives in your session, so it lasts from page to
// page while you click around, and starts over when you press Run.
if (!isset($_SESSION['pets'])) {
    $_SESSION['pets'] = ['cat', 'dog'];
}
$pets = $_SESSION['pets'];

$title = 'My Pet List';
include 'includes/header.php';
?>

<ul>
  <?php foreach ($pets as $p): ?>
    <li><a href="pet.php?name=<?= urlencode($p) ?>"><?= htmlspecialchars($p) ?></a></li>
  <?php endforeach; ?>
</ul>

<form method="post" action="add.php">
  <input name="name" placeholder="a new pet">
  <button>Add</button>
</form>

<?php
include 'includes/footer.php';

// ---------------------------------------------------------------------------
// USING A DATABASE INSTEAD OF A LIST
//
// Add a file called schema.sql to this project, put CREATE TABLE and INSERT
// statements in it, and press Run. It is built into a real database called
// data.db sitting next to this file, from scratch, every single time you Run
// -- so you cannot break it, and anything you INSERT while the site is
// running is gone on the next Run.
//
// Then, in any page:
//
// $db = new PDO('sqlite:data.db');
//
// // SQLite IGNORES FOREIGN KEYS UNLESS YOU ASK, ON EVERY CONNECTION.
// $db->exec('PRAGMA foreign_keys = ON');
//
// // ALWAYS a ? for a value that came from a visitor, never the value glued
// // into the SQL: that is how a site gets broken into (SQL injection).
// $stmt = $db->prepare('SELECT name, department FROM teachers WHERE department = ?');
// $stmt->execute([$_GET['dept'] ?? 'Math']);
// foreach ($stmt as $row) {
//     echo htmlspecialchars($row['name']) . '<br>';
// }
