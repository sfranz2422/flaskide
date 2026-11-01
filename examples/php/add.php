<?php
// The form on index.php sends its boxes here, in $_POST.
session_start();

$name = trim($_POST['name'] ?? '');
if ($name !== '') {
    $_SESSION['pets'][] = $name;
}

// Then straight back to the list. header('Location: ...') sends the browser
// to another page; exit stops this one, so nothing after it runs.
header('Location: index.php');
exit;
