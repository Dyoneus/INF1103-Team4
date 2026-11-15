// Show the "assessing" overlay while a form that calls the AI is being submitted.
document.querySelectorAll("form[data-busy]").forEach(function (form) {
  form.addEventListener("submit", function () {
    document.getElementById("busy").hidden = false;
    form.querySelectorAll("button[type=submit]").forEach(function (button) {
      button.disabled = true;
    });
  });
});

// Coming back with the browser's Back button must not leave the overlay up.
window.addEventListener("pageshow", function () {
  document.getElementById("busy").hidden = true;
  document.querySelectorAll("button[type=submit]").forEach(function (button) {
    button.disabled = false;
  });
});
