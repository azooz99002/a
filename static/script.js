document.addEventListener("DOMContentLoaded", () => {
  const trainersPanel = document.getElementById("trainers-panel");
  const subjectsPanel = document.getElementById("subjects-panel");
  const toggleTrainers = document.getElementById("toggle-trainers");
  const toggleSubjects = document.getElementById("toggle-subjects");

  if (toggleTrainers && trainersPanel) {
    toggleTrainers.addEventListener("click", () => {
      trainersPanel.classList.toggle("d-none");
    });
  }

  if (toggleSubjects && subjectsPanel) {
    toggleSubjects.addEventListener("click", () => {
      subjectsPanel.classList.toggle("d-none");
    });
  }

  const editModal = document.getElementById("editScheduleModal");
  const scheduleForm = document.getElementById("scheduleForm");
  if (editModal && scheduleForm) {
    const trainerSelect = document.getElementById("editTrainer");
    const subjectSelect = document.getElementById("editSubject");
    const daySelect = document.getElementById("editDay");
    const startSlotSelect = document.getElementById("editStartSlot");
    const durationInput = document.getElementById("editDuration");
    const sectionInput = document.getElementById("editSection");
    const slotCount = Number(editModal.dataset.slotCount || "0");
    const createAction = editModal.dataset.createAction || scheduleForm.getAttribute("action");

    if (durationInput && slotCount) {
      durationInput.max = slotCount;
    }

    document.querySelectorAll(".edit-schedule-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const scheduleId = button.dataset.scheduleId;
        if (!scheduleId) return;
        scheduleForm.action = `/schedule/${scheduleId}/update`;

        if (trainerSelect) {
          trainerSelect.value = button.dataset.trainerId || "";
        }
        if (subjectSelect) {
          subjectSelect.value = button.dataset.subjectId || "";
        }
        if (daySelect) {
          daySelect.value = button.dataset.day || "";
        }
        if (startSlotSelect) {
          startSlotSelect.value = button.dataset.startSlot || "0";
        }
        if (durationInput) {
          durationInput.value = button.dataset.durationSlots || "1";
        }
        if (sectionInput) {
          sectionInput.value = button.dataset.section || "";
        }
      });
    });

    document.querySelectorAll(".create-schedule-btn").forEach((button) => {
      button.addEventListener("click", () => {
        scheduleForm.action = createAction;
        scheduleForm.reset();
        if (trainerSelect && trainerSelect.options.length) {
          trainerSelect.selectedIndex = 0;
        }
        if (subjectSelect && subjectSelect.options.length) {
          subjectSelect.selectedIndex = 0;
        }
        if (daySelect && daySelect.options.length) {
          daySelect.selectedIndex = 0;
        }
        if (startSlotSelect) {
          startSlotSelect.value = "0";
        }
        if (durationInput) {
          durationInput.value = "1";
        }
        if (sectionInput) {
          sectionInput.value = "";
        }
      });
    });
  }

  document.querySelectorAll(".reset-data-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const confirmed = window.confirm("سيتم مسح جميع البيانات من النظام. هل أنت متأكد؟");
      if (!confirmed) {
        event.preventDefault();
      }
    });
  });
});
