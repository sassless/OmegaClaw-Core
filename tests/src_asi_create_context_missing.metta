!(import! &self ./tests/lib/utils)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/plugin)
!(import! &self ./src/skills)
!(import! &self ./src/loop)

(= (set-test-memory-directory $path)
   (progn
     (collapse
       (match &self (= (memoryDirectory) $body)
         (remove-atom &self (= (memoryDirectory) $body))))
     (add-atom &self (= (memoryDirectory) $path))))

!(initLogger)
!(test
   (progn
     (set-test-memory-directory "./tests/res/missing-context-directory")
     (loadMettaPlugin "asi_create_context" "./plugins/asi_create_context")
     (repr (collapse (prompt-extension asi-create-context))))
   "()")
