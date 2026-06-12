/*
 * Progressive enhancement for the clip upload form: drag-and-drop file
 * selection and an XHR upload with a real progress bar. Without JS the
 * plain form still posts and the server re-renders errors as usual.
 */
(function () {
    'use strict';

    const form = document.querySelector('.js-upload-form');
    if (!form) return;

    const input = form.querySelector('input[type="file"]');
    const dropzone = form.querySelector('.js-dropzone');
    const chip = form.querySelector('.js-file-chip');
    const chipName = form.querySelector('.js-file-name');
    const chipSize = form.querySelector('.js-file-size');
    const removeBtn = form.querySelector('.js-file-remove');
    const errorsBox = form.querySelector('.js-form-errors');
    const progress = form.querySelector('.js-progress');
    const progressBar = form.querySelector('.js-progress-bar');
    const progressText = form.querySelector('.js-progress-text');
    const submitBtn = form.querySelector('.js-submit');

    const maxSize = parseInt(form.dataset.maxSize, 10);
    const allowedExtensions = form.dataset.extensions.split(',');
    const DRAG_CLASSES = ['border-ember-500', 'bg-ink-800'];

    // JS is running: swap the native input for the dropzone.
    input.hidden = true;
    dropzone.hidden = false;

    function formatSize(bytes) {
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function showErrors(messages) {
        errorsBox.replaceChildren(
            ...messages.map(function (msg) {
                const li = document.createElement('li');
                li.textContent = msg;
                return li;
            })
        );
        errorsBox.hidden = messages.length === 0;
    }

    function validate(file) {
        const ext = ('.' + file.name.split('.').pop()).toLowerCase();
        if (!allowedExtensions.includes(ext)) {
            return 'Unsupported file type "' + ext + '". Allowed: ' + allowedExtensions.join(', ') + '.';
        }
        if (file.size > maxSize) {
            return 'File is too large (' + formatSize(file.size) + '). The maximum is ' + formatSize(maxSize) + '.';
        }
        return null;
    }

    function setFile(files) {
        const file = files && files[0];
        if (!file) return;
        const problem = validate(file);
        if (problem) {
            showErrors([problem]);
            return;
        }
        showErrors([]);
        if (input.files !== files) input.files = files;
        chipName.textContent = file.name;
        chipSize.textContent = formatSize(file.size);
        chip.hidden = false;
        dropzone.hidden = true;
    }

    function clearFile() {
        input.value = '';
        chip.hidden = true;
        dropzone.hidden = false;
    }

    dropzone.addEventListener('click', function () { input.click(); });
    dropzone.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            input.click();
        }
    });
    input.addEventListener('change', function () { setFile(input.files); });
    removeBtn.addEventListener('click', clearFile);

    ['dragenter', 'dragover'].forEach(function (type) {
        dropzone.addEventListener(type, function (e) {
            e.preventDefault();
            dropzone.classList.add(...DRAG_CLASSES);
        });
    });
    ['dragleave', 'drop'].forEach(function (type) {
        dropzone.addEventListener(type, function (e) {
            e.preventDefault();
            dropzone.classList.remove(...DRAG_CLASSES);
        });
    });
    dropzone.addEventListener('drop', function (e) {
        setFile(e.dataTransfer.files);
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!input.files.length) {
            showErrors(['Choose a video file to upload.']);
            return;
        }
        showErrors([]);
        submitBtn.disabled = true;
        submitBtn.textContent = 'Uploading…';
        progress.hidden = false;

        const xhr = new XMLHttpRequest();
        xhr.open('POST', form.action || window.location.href);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        xhr.responseType = 'json';

        xhr.upload.addEventListener('progress', function (ev) {
            if (!ev.lengthComputable) return;
            const percent = Math.round((ev.loaded / ev.total) * 100);
            progressBar.style.width = percent + '%';
            if (percent < 100) {
                progressText.textContent =
                    'Uploading… ' + percent + '% (' + formatSize(ev.loaded) + ' of ' + formatSize(ev.total) + ')';
            } else {
                // Upload is done but the server still probes the video.
                progressText.textContent = 'Upload complete — checking your clip…';
            }
        });

        function fail(messages) {
            progress.hidden = true;
            progressBar.style.width = '0';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Upload clip';
            showErrors(messages);
        }

        xhr.addEventListener('load', function () {
            const data = xhr.response;
            if (xhr.status === 200 && data && data.redirect) {
                window.location.assign(data.redirect);
            } else if (xhr.status === 400 && data && data.errors) {
                fail(
                    Object.entries(data.errors).flatMap(function (entry) {
                        return entry[1];
                    })
                );
            } else {
                fail(['Something went wrong while uploading. Please try again.']);
            }
        });
        xhr.addEventListener('error', function () {
            fail(['Network error — check your connection and try again.']);
        });

        xhr.send(new FormData(form));
    });
})();
