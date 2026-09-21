-- Provisioning snapshot for the verified EM8695 subscriber.
-- WARNING: this file contains the subscriber identity, K, OPc, and SQN.

START TRANSACTION;

INSERT INTO AuthenticationSubscription
  (ueid, authenticationMethod, encPermanentKey, protectionParameterId,
   sequenceNumber, authenticationManagementField, algorithmId, encOpcKey,
   encTopcKey, vectorGenerationInHss, n5gcAuthMethod, rgAuthenticationInd, supi)
VALUES
  ('001010000134378', '5G_AKA', '0772f723eb02ff1137469c8a15413f9c',
   '0772f723eb02ff1137469c8a15413f9c',
   '{"sqn":"000000001161","sqnScheme":"NON_TIME_BASED","lastIndexes":{"ausf":0}}',
   '8000', 'milenage', 'e4058703611cadaf283cefb9965b9f4e',
   NULL, NULL, NULL, NULL, '001010000134378')
ON DUPLICATE KEY UPDATE
  authenticationMethod=VALUES(authenticationMethod),
  encPermanentKey=VALUES(encPermanentKey),
  protectionParameterId=VALUES(protectionParameterId),
  sequenceNumber=VALUES(sequenceNumber),
  authenticationManagementField=VALUES(authenticationManagementField),
  algorithmId=VALUES(algorithmId),
  encOpcKey=VALUES(encOpcKey),
  encTopcKey=VALUES(encTopcKey),
  vectorGenerationInHss=VALUES(vectorGenerationInHss),
  n5gcAuthMethod=VALUES(n5gcAuthMethod),
  rgAuthenticationInd=VALUES(rgAuthenticationInd),
  supi=VALUES(supi);

INSERT INTO SessionManagementSubscriptionData
  (ueid, servingPlmnid, singleNssai, dnnConfigurations)
VALUES
  ('001010000134378', '00101',
   '{"sd":"FFFFFF","sst":1}',
   '{"oai":{"sscModes":{"defaultSscMode":"SSC_MODE_1"},"sessionAmbr":{"uplink":"1000Mbps","downlink":"1000Mbps"},"5gQosProfile":{"5qi":6,"arp":{"preemptCap":"NOT_PREEMPT","preemptVuln":"PREEMPTABLE","priorityLevel":15},"priorityLevel":1},"pduSessionTypes":{"defaultSessionType":"IPV4"},"staticIpAddress":[{"ipv4Addr":"10.0.0.6"}]}}')
ON DUPLICATE KEY UPDATE
  singleNssai=VALUES(singleNssai),
  dnnConfigurations=VALUES(dnnConfigurations);

COMMIT;
