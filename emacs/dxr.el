(require 'easymenu)
(require 'etags)
(require 'ring)

(make-variable-buffer-local 'dxr-root)
(make-variable-buffer-local 'dxr-self)
(make-variable-buffer-local 'dxr-overlays)
(make-variable-buffer-local 'dxr-decl)

(defvar dxr-find-keymap (make-sparse-keymap "Find")
  "Keymap used in dxr overlays")

(define-key dxr-find-keymap (kbd "M-RET") 'dxr-on-click)
(define-key dxr-find-keymap (kbd "C-c C-c") 'dxr-on-click)

(defun dxr-find-id (point)
  (interactive "d")
  (let (dxr-id)
    (mapc (lambda (o)
	    (let ((id (overlay-get o 'dxr-id)))
	      (and id (setq dxr-id id))))
	  (overlays-at point))
    dxr-id))

(defun dxr-run-info (key)
  (interactive)
  (ring-insert find-tag-marker-ring (point-marker))
  (compilation-start (format "cd %s; dxr-lookup.py info %s %s %s %s" dxr-root
			     (nth 0 key)
			     (nth 1 key)
			     (nth 2 key)
			     (nth 3 key)) 'grep-mode))

(defun dxr-on-click (point)
  (interactive "d")
  (let ((dxr-id (dxr-find-id point)))
    (cond ((eq 'include (car dxr-id))
	   (ring-insert find-tag-marker-ring (point-marker))
	   (find-file (expand-file-name (cadr dxr-id) dxr-root)))
	  (dxr-id (dxr-run-info dxr-id)))))

(defun dxr-make-overlay (key start end)
    (let ((overlay (make-overlay (1+ start) (1+ end))))
      (overlay-put overlay 'keymap dxr-find-keymap)
      (overlay-put overlay 'mouse-face 'highlight)
      (overlay-put overlay 'dxr-id key)
      (puthash key (cons overlay (gethash key dxr-overlays nil))
	       dxr-overlays)))

(defun dxr-make-key (kind id)
  (cons kind id))

(defun dxr-decorate-buffer ()
  (interactive)
  (cond
   (dxr-overlays
    (maphash (lambda (key vals)
	       (mapc 'delete-overlay vals)) dxr-overlays)
    (setq dxr-overlays nil)))
  (setq dxr-overlays (make-hash-table :test 'equal))
  (setq dxr-decl (make-hash-table :test 'equal))
  (let ((fn (buffer-file-name))
	(dxr-buffer (generate-new-buffer " *dxr*"))
	d)
    (call-process-shell-command "dxr-lookup.py" nil dxr-buffer nil
				"decorate" fn)
    (with-current-buffer dxr-buffer
      (insert "nil\n")
      (goto-char (point-min)))
    (while (setq d (read dxr-buffer))
      (let ((cmd (car d))
	    (kind (nth 1 d))
	    (args (nthcdr 2 d)))
	(cond ((eq cmd 'root)
	       (setq dxr-root kind))
	      ((eq cmd 'self)
	       (setq dxr-self kind))
	      ((eq cmd 'include)
	       (mapc (lambda (arg)
		       (dxr-make-overlay (list 'include (nth 2 arg)) (nth 0 arg) (nth 1 arg)))
		     (nthcdr 1 d)))
	      ((eq cmd 'r)
	       (let ((id (nth 0 args))
		     (line (nth 1 args))
		     (col (nth 2 args))
		     (start (nth 3 args))
		     (end (nth 4 args)))
		 (dxr-make-overlay (dxr-make-key kind (list id line col)) start end)))
	      ((eq cmd 'decl)
	       (let ((id (nth 0 args))
		     (line (nth 1 args))
		     (col (nth 2 args))
		     (name (nth 3 args))
		     (type (and (> (length args) 4)
				(nth 4 args))))
		 (puthash (list kind id line col)
			  (if type
			      (cons name type)
			    name) dxr-decl)))
	       )))
    (kill-buffer dxr-buffer)))

(provide 'dxr)
