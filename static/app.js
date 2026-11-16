// Show the "assessing" overlay while a form that calls the AI is being submitted.
document.querySelectorAll("form[data-busy]").forEach(function (form) {
  form.addEventListener("submit", function () {
    document.getElementById("busy").hidden = false;
    form.querySelectorAll("button[type=submit]").forEach(function (button) {
      button.disabled = true;
    });
  });
});

// Ask before a destructive action such as deleting a report.
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

// Coming back with the browser's Back button must not leave the overlay up.
window.addEventListener("pageshow", function () {
  document.getElementById("busy").hidden = true;
  document.querySelectorAll("button[type=submit]").forEach(function (button) {
    button.disabled = false;
  });
});

// Photo picker: a file input normally replaces its selection on every pick.
// Keep a running list instead, so photos can be added one at a time (up to the
// limit) and removed individually. The input's FileList is rebuilt each time,
// so the form still submits every chosen photo under the "photos" field.
(function () {
  var input = document.getElementById("photos");
  var list = document.getElementById("photo-list");
  var limitMessage = document.getElementById("photo-limit");
  if (!input || !list || typeof DataTransfer === "undefined") {
    return; // Older browsers keep the default behaviour.
  }
  var maxPhotos = parseInt(input.dataset.maxPhotos, 10) || 3;
  var chosen = [];

  function key(file) {
    return file.name + "|" + file.size + "|" + file.lastModified;
  }

  function sync() {
    var transfer = new DataTransfer();
    chosen.forEach(function (file) { transfer.items.add(file); });
    input.files = transfer.files;

    list.innerHTML = "";
    chosen.forEach(function (file, index) {
      var item = document.createElement("li");
      var name = document.createElement("span");
      name.className = "photo-name";
      name.textContent = file.name;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", "Remove " + file.name);
      remove.addEventListener("click", function () {
        chosen.splice(index, 1);
        limitMessage.hidden = true;
        sync();
      });
      item.appendChild(name);
      item.appendChild(remove);
      list.appendChild(item);
    });
    list.hidden = chosen.length === 0;
  }

  input.addEventListener("change", function () {
    var skipped = 0;
    Array.prototype.forEach.call(input.files, function (file) {
      var duplicate = chosen.some(function (existing) { return key(existing) === key(file); });
      if (duplicate) {
        return;
      }
      if (chosen.length < maxPhotos) {
        chosen.push(file);
      } else {
        skipped += 1;
      }
    });
    if (skipped) {
      limitMessage.textContent = "You can attach at most " + maxPhotos +
        " photos. " + skipped + " extra photo" + (skipped === 1 ? " was" : "s were") + " not added.";
      limitMessage.hidden = false;
    } else {
      limitMessage.hidden = true;
    }
    sync();
  });
})();
