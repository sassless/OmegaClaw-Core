!(import! &self ./tests/lib/utils)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ../src/helper.py)
!(import! &self ../src/config.py)
!(import! &self ./src/config)
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

!(set-test-memory-directory "/sys")
!(loadMettaPlugin "workflow" "./plugins/workflow")

!(test (contains-text (getPromptExtensions) "Available workflows") True)
!(test (contains-text (getPromptExtensions) "extensions-hub: ") True)
