;configured at runtime:
(= (commchannel) (empty))

;Connect all the channels:
(= (initChannels)
   (progn (log INFO "channels" "Initializing channels")
          (configure commchannel irc)
          (commChannelStart (commchannel))))

(= (commChannelStart $commchannel)
   (py-call (channels.commChannelStart $commchannel)))

(= (commChannelReceive)
   (py-call (channels.commChannelReceive)))

(= (commChannelSend $message)
   (py-call (channels.commChannelSend $message)))

(= (commChannelSendAttachment $attachment-id $message)
   (py-call (channels.commChannelSendAttachment $attachment-id $message)))

;Receive the latest user message considering all communication channels:
(= (receive)
   (commChannelReceive))

;Send a message to all communication channels:
!(change-state! &lastsend "")
!(change-state! &lastsendattachment "")
(= (send $msg)
   (if (!= $msg (get-state &lastsend))
       (progn (change-state! &lastsend $msg)
              (let $safemsg (string-replace $msg  "\n" "\\n")
                   (let $temp (cut) (commChannelSend $safemsg)))) _))

(= (send-attachment $attachment-id $msg)
   (if (or (== $attachment-id "") (== $msg ""))
       SEND-ATTACHMENT-INVALID-ARGUMENT
       (let $sendkey (py-str ($attachment-id "|" $msg))
         (if (== $sendkey (get-state &lastsendattachment))
             SEND-ATTACHMENT-SUCCESS
             (let $safemsg (string-replace $msg "\n" "\\n")
               (if (commChannelSendAttachment $attachment-id $safemsg)
                   (progn
                     (change-state! &lastsendattachment $sendkey)
                     SEND-ATTACHMENT-SUCCESS)
                   SEND-ATTACHMENT-UNSUPPORTED-CHANNEL))))))
