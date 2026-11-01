<?php
// pet.php?name=cat -- what comes after the ? is in $_GET.
$name = $_GET['name'] ?? 'nobody';

$title = $name;
include 'includes/header.php';
?>

<p>This one is called <strong><?= htmlspecialchars($name) ?></strong>.</p>
<p><a href="index.php">back to the list</a></p>

<?php include 'includes/footer.php'; ?>
