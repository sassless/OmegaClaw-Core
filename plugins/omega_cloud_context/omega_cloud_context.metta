(= (omega-cloud-context-path)
   (py-call (context_file.context_path (memoryDirectory))))

(= (omega-cloud-context)
   (let $text (py-call (context_file.read_context (omega-cloud-context-path)))
     (if (== $text "") (empty) $text)))

(= (loadOmegaCloudContextPlugin)
   (let $path (omega-cloud-context-path)
     (progn
       (log INFO "omega_cloud_context"
         (strings-concat ("Using Omega Cloud context file: " $path)))
       (add-atom &self
         (= (prompt-extension omega-cloud-context)
            (let $text (py-call (context_file.read_context $path))
              (if (== $text "") (empty) $text))))
       ())))

(= (loadOmegaPlugin) (loadOmegaCloudContextPlugin))
(= (loadOmegaClawPlugin) (loadOmegaCloudContextPlugin))
