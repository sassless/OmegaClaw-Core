(= (loadWschatPlugin)
   (progn
     (py-call (asi_wschat.loadOmegaPlugin))
     (add-atom &self
       (= (send-attachment $attachment-id $message)
          (if (or (== $attachment-id "") (== $message ""))
              SEND-ATTACHMENT-INVALID-ARGUMENT
              (let $once (cut)
                (if (py-call (asi_wschat.send_attachment_skill $attachment-id $message))
                    SEND-ATTACHMENT-SUCCESS
                    SEND-ATTACHMENT-FAILED)))))
     (add-skill send-attachment
       "Send a previously uploaded file as an attachment using its one-use id"
       (attachment_id message))
     ()))

(= (loadOmegaPlugin) (loadWschatPlugin))
(= (loadOmegaClawPlugin) (loadWschatPlugin))
