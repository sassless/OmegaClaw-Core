(= (asi-create-context-path)
   (py-call (context_file.context_path (memoryDirectory))))

(= (asi-create-context)
   (let $text (py-call (context_file.read_context (asi-create-context-path)))
     (if (== $text "") (empty) $text)))

(= (loadOmegaClawPlugin)
   (let $path (asi-create-context-path)
     (progn
       (log INFO "asi_create_context"
         (strings-concat ("Using ASI Create context file: " $path)))
       (add-atom &self
         (= (prompt-extension asi-create-context)
            (let $text (py-call (context_file.read_context $path))
              (if (== $text "") (empty) $text))))
       ())))
